import logging
import signal
import threading
import time
from datetime import datetime
from xml.etree.ElementTree import fromstring

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import create_tables, get_db_session
from osm_changeset_loader.model import Changeset, Metadata
from osm_changeset_loader.path import Path
from osm_changeset_loader.replication import ReplicationClient
from sqlalchemy.dialects.postgresql import insert

config = Config()
replication_client = ReplicationClient(config)

# Global bounding box
BBOX = [-180, -90, 180, 90]

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def init_db():
    """
    Initialize the database.
    """
    create_tables()


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

    values = [
        {
            "id": cs.id,
            "user": cs.user,
            "uid": cs.uid,
            "created_at": cs.created_at,
            "closed_at": cs.closed_at,
            "open": cs.open,
            "min_lat": cs.min_lat,
            "min_lon": cs.min_lon,
            "max_lat": cs.max_lat,
            "max_lon": cs.max_lon,
            "bbox_area_km2": cs.bbox_area_km2,
            "centroid_lon": cs.centroid_lon,
            "centroid_lat": cs.centroid_lat,
        }
        for cs in changesets
    ]
    if len(values) == 0:
        logging.info("No changesets to insert.")
        return False

    statement = insert(Changeset).values(values)
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
            "bbox_area_km2": statement.excluded.bbox_area_km2,
            "centroid_lon": statement.excluded.centroid_lon,
            "centroid_lat": statement.excluded.centroid_lat,
        },
    )

    try:
        session.execute(do_update)
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
            time.sleep(60)
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

        time.sleep(60)  # Wait before next check


def process_historical_changes(stop_event):
    """
    Process historical changes going backwards in time.
    """
    while not stop_event.is_set():
        local_state = get_local_state()
        if local_state.sequence <= 1:
            logging.info("Reached beginning of history")
            return

        target_sequence = max(1, local_state.sequence - 1000)  # Process in chunks
        current_sequence = local_state.sequence - 1

        while current_sequence >= target_sequence and not stop_event.is_set():
            current_path = Path(sequence=current_sequence)
            logging.info(f"Processing historical sequence {current_sequence}")

            changesets = replication_client.get_changesets(current_path)
            if changesets:
                if insert_changesets(changesets):
                    set_local_state(current_path)

            current_sequence -= 1

        # time.sleep(60)  # Pause between chunks


def catch_up():
    """
    Run two threads: one for recent changes and one for historical backfill.
    """
    stop_event = threading.Event()

    recent_thread = threading.Thread(
        target=process_recent_changes, args=(stop_event,), name="recent-changes"
    )
    historical_thread = threading.Thread(
        target=process_historical_changes, args=(stop_event,), name="historical-changes"
    )

    recent_thread.start()
    historical_thread.start()

    try:
        recent_thread.join()
        historical_thread.join()
    except KeyboardInterrupt:
        logging.info("Stopping threads...")
        stop_event.set()
        recent_thread.join()
        historical_thread.join()


def handle_exit(signum, frame):
    logging.info("Exiting gracefully...")
    # The main thread will handle cleanup
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    init_db()
    catch_up()
