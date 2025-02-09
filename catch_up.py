import logging
import signal
import threading
import time
from datetime import datetime
from xml.etree.ElementTree import fromstring
from concurrent.futures import ThreadPoolExecutor, as_completed

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import create_tables, get_db_session
from osm_changeset_loader.model import (
    Changeset,
    Metadata,
    ChangesetTag,
    ChangesetComment,
)
from osm_changeset_loader.path import Path
from osm_changeset_loader.replication import ReplicationClient
from sqlalchemy.dialects.postgresql import insert

config = Config()
replication_client = ReplicationClient(config)

# Global bounding box, unused right now
BBOX = [-180, -90, 180, 90]

# Number of threads for historical processing
HISTORICAL_THREADS = 8

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_local_state():
    """
    Get the local state from the database.
    """
    session = get_db_session()
    state = session.query(Metadata).order_by(Metadata.timestamp).first()
    if state:
        return Path(sequence=int(state.state))
    else:
        return Path(sequence=0)


def set_local_state(state):
    """
    Set the local state in the database.
    """
    session = get_db_session()
    metadata = Metadata(state=str(state.sequence), timestamp=datetime.now())
    session.add(metadata)
    session.commit()


def insert_changesets(changesets):
    """
    Insert changesets into database.
    """
    session = get_db_session()

    try:
        for cs in changesets:
            # Insert or update the changeset
            statement = insert(Changeset).values(
                id=cs.id,
                user=cs.user,
                uid=cs.uid,
                created_at=cs.created_at,
                closed_at=cs.closed_at,
                open=cs.open,
                min_lat=cs.min_lat,
                min_lon=cs.min_lon,
                max_lat=cs.max_lat,
                max_lon=cs.max_lon,
            )
            do_update = statement.on_conflict_do_update(
                index_elements=[Changeset.id],
                set_={
                    "user": statement.excluded.user,
                    "uid": statement.excluded.uid,
                    "created_at": statement.excluded.created_at,
                    "closed_at": statement.excluded.closed_at,
                    "open": statement.excluded.open,
                    "min_lat": statement.excluded.min_lat,
                    "min_lon": statement.excluded.min_lon,
                    "max_lat": statement.excluded.max_lat,
                    "max_lon": statement.excluded.max_lon,
                },
            )
            session.execute(do_update)

            # Delete existing tags and comments for this changeset
            session.query(ChangesetTag).filter(
                ChangesetTag.changeset_id == cs.id
            ).delete()
            session.query(ChangesetComment).filter(
                ChangesetComment.changeset_id == cs.id
            ).delete()

            # Insert new tags
            for tag in cs.tags:
                session.add(ChangesetTag(changeset_id=cs.id, k=tag.k, v=tag.v))

            # Insert new comments
            for comment in cs.comments:
                session.add(
                    ChangesetComment(
                        changeset_id=cs.id,
                        uid=comment.uid,
                        user=comment.user,
                        date=comment.date,
                        text=comment.text,
                    )
                )

        session.commit()
        return True
    except Exception as e:
        logging.error(f"Error inserting changesets: {e}")
        session.rollback()
        return False


def process_recent_changes(stop_event):
    """
    Monitor and process recent changes from the replication API.
    """
    while not stop_event.is_set():
        latest_path = replication_client.get_remote_state()
        if not latest_path:
            logging.error("Failed to get remote state, retrying in 60 seconds")
            time.sleep(config.SLEEP_INTERVAL)
            continue

        local_state = get_local_state()
        current_sequence = latest_path.sequence

        while current_sequence > local_state.sequence and not stop_event.is_set():
            current_path = Path(sequence=current_sequence)
            logging.info(f"Processing recent sequence {current_sequence}")

            changesets = replication_client.get_changesets(current_path)
            if changesets:
                if insert_changesets(changesets):
                    set_local_state(current_path)

            current_sequence -= 1

        time.sleep(config.SLEEP_INTERVAL)  # Wait before next check


def process_historical_range(start_sequence, end_sequence, stop_event):
    """
    Process a range of historical changes.
    """
    current_sequence = start_sequence
    while current_sequence >= end_sequence and not stop_event.is_set():
        current_path = Path(sequence=current_sequence)
        logging.info(f"Processing historical sequence {current_sequence}")

        changesets = replication_client.get_changesets(current_path)
        if changesets:
            if insert_changesets(changesets):
                set_local_state(current_path)

        current_sequence -= 1


def process_historical_changes(stop_event, thread_id):
    """
    Process historical changes going backwards in time for a specific thread.
    """
    while not stop_event.is_set():
        local_state = get_local_state()
        if local_state.sequence <= 1:
            logging.info(f"Thread {thread_id} reached beginning of history")
            return

        # Each thread processes a different chunk of sequences
        chunk_size = 1000
        start_sequence = local_state.sequence - (thread_id * chunk_size)
        end_sequence = max(1, start_sequence - chunk_size)

        if start_sequence <= 0:
            logging.info(f"Thread {thread_id} has no more work to do")
            return

        logging.info(
            f"Thread {thread_id} processing sequences {start_sequence} to {end_sequence}"
        )
        process_historical_range(start_sequence, end_sequence, stop_event)

        # Wait a bit before checking for more work
        time.sleep(1)


def catch_up():
    """
    Run multiple threads: one for recent changes and multiple for historical backfill.
    """
    stop_event = threading.Event()

    # Start recent changes thread
    recent_thread = threading.Thread(
        target=process_recent_changes, args=(stop_event,), name="recent-changes"
    )
    recent_thread.start()

    # Start historical processing threads
    historical_threads = []
    for i in range(HISTORICAL_THREADS):
        thread = threading.Thread(
            target=process_historical_changes,
            args=(stop_event, i),
            name=f"historical-changes-{i}",
        )
        thread.start()
        historical_threads.append(thread)

    try:
        # Monitor threads and restart historical ones if they finish early
        while not stop_event.is_set():
            for i, thread in enumerate(historical_threads):
                if not thread.is_alive():
                    logging.info(f"Restarting historical thread {i}")
                    new_thread = threading.Thread(
                        target=process_historical_changes,
                        args=(stop_event, i),
                        name=f"historical-changes-{i}",
                    )
                    new_thread.start()
                    historical_threads[i] = new_thread

            time.sleep(5)  # Check thread status every 5 seconds

    except KeyboardInterrupt:
        logging.info("Stopping threads...")
        stop_event.set()

    # Wait for all threads to finish
    recent_thread.join()
    for thread in historical_threads:
        thread.join()


def handle_exit(signum, frame):
    logging.info("Exiting gracefully...")
    # The main thread will handle cleanup
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    catch_up()
