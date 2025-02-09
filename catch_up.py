import logging
import signal
import threading
import time
import queue
from datetime import datetime
from xml.etree.ElementTree import fromstring
from concurrent.futures import ThreadPoolExecutor

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import create_tables, get_db_session
from osm_changeset_loader.model import Changeset, ChangesetTag, ChangesetComment
from osm_changeset_loader.path import Path
from osm_changeset_loader.replication import ReplicationClient
from sqlalchemy.dialects.postgresql import insert
from contextlib import contextmanager

# ------------------------------------------------------------------------------
# Configuration and Globals
# ------------------------------------------------------------------------------

config = Config()
replication_client = ReplicationClient(config)

# Number of threads for historical processing
HISTORICAL_THREADS = 8
CHUNK_SIZE = 1000  # Number of sequences per historical chunk

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Lock for safely updating shared metadata
local_state_lock = threading.Lock()

# ------------------------------------------------------------------------------
# Session Management
# ------------------------------------------------------------------------------


@contextmanager
def session_scope():
    session = get_db_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


# ------------------------------------------------------------------------------
# Get Latest Processed Changeset
# ------------------------------------------------------------------------------


def get_latest_changeset_id() -> int:
    """Retrieve the latest processed changeset ID from the database."""
    with session_scope() as session:
        latest = session.query(Changeset.id).order_by(Changeset.id.desc()).first()
        return latest[0] if latest else 0


def get_sequence_for_changeset(changeset_id: int) -> int:
    """
    Get the sequence number for a given changeset ID by querying the replication API.
    Returns the sequence number or None if not found.
    """
    # Start from current state and work backwards
    current = replication_client.get_remote_state()
    while current and current.sequence > 0:
        changesets = replication_client.get_changesets(current)
        if changesets:
            if min(cs.id for cs in changesets) <= changeset_id <= max(cs.id for cs in changesets):
                return current.sequence
            # If we've gone too far back
            if min(cs.id for cs in changesets) < changeset_id:
                return current.sequence + 1
        current = Path(sequence=current.sequence - 1)
    return 1


# ------------------------------------------------------------------------------
# Database Insertion for Changesets
# ------------------------------------------------------------------------------


def insert_changesets_bulk(changesets) -> bool:
    """Bulk insert or update changesets to optimize database performance."""
    try:
        with session_scope() as session:
            session.bulk_insert_mappings(Changeset, [cs.to_dict() for cs in changesets])
        return True
    except Exception as e:
        logging.error(f"Error inserting changesets: {e}")
        return False


# ------------------------------------------------------------------------------
# Worker Functions
# ------------------------------------------------------------------------------


def process_sequence(sequence: int) -> bool:
    """
    Process a single replication sequence.
    Fetches and inserts changesets while handling network errors.
    """
    try:
        current_path = Path(sequence=sequence)
        logging.info(f"Processing sequence {sequence}")
        changesets = replication_client.get_changesets(current_path)
        if changesets:
            return insert_changesets_bulk(changesets)
    except Exception as e:
        logging.error(f"Error processing sequence {sequence}: {e}")
    return False


def recent_worker(stop_event: threading.Event):
    """
    Continuously process the most recent changeset sequence.
    Runs every minute to stay up to date.
    """
    while not stop_event.is_set():
        try:
            current = replication_client.get_remote_state()
            if current:
                success = process_sequence(current.sequence)
                if not success:
                    logging.error(f"Failed to process sequence {current.sequence}")
            # Wait for next minute
            time.sleep(60)
        except Exception as e:
            logging.error(f"Error in recent worker: {e}")
            time.sleep(60)  # Wait before retry


def historical_worker(stop_event: threading.Event, task_queue: queue.Queue):
    """
    Process historical changesets using a task queue.
    """
    while not stop_event.is_set():
        try:
            start_sequence, end_sequence = task_queue.get_nowait()
        except queue.Empty:
            break

        logging.info(f"Processing chunk: {start_sequence} to {end_sequence}")
        for sequence in range(start_sequence, end_sequence + 1):
            if stop_event.is_set():
                break
            success = process_sequence(sequence)
            if not success:
                logging.error(f"Failed to process sequence {sequence}, retrying later.")
            time.sleep(0.1)

        task_queue.task_done()


# ------------------------------------------------------------------------------
# Main Catch-Up Function
# ------------------------------------------------------------------------------


def catch_up():
    stop_event = threading.Event()

    # Signal handlers for graceful exit
    signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())
    signal.signal(signal.SIGINT, lambda s, f: stop_event.set())

    # Get latest processed changeset and its sequence
    latest_id = get_latest_changeset_id()
    if latest_id:
        historical_start = get_sequence_for_changeset(latest_id)
        logging.info(f"Starting from changeset ID {latest_id} (sequence {historical_start})")
    else:
        historical_start = 1
        logging.info("No existing changesets found, starting from beginning")

    # Recent processing thread
    recent_thread = threading.Thread(
        target=recent_worker,
        args=(stop_event,),
        name="recent-worker",
    )
    recent_thread.start()

    # Build historical task queue (for sequences from 1 to historical_start)
    historical_queue = queue.Queue()
    start = 1
    while start < historical_start:
        end = min(historical_start, start + CHUNK_SIZE - 1)
        historical_queue.put((start, end))
        start = end + 1

    # Process historical chunks using thread pool
    with ThreadPoolExecutor(max_workers=HISTORICAL_THREADS) as executor:
        futures = [
            executor.submit(historical_worker, stop_event, historical_queue)
            for _ in range(HISTORICAL_THREADS)
        ]

        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            logging.info("Interrupted! Stopping historical processing.")
            stop_event.set()

    # Wait for recent processing to complete
    recent_thread.join()

    logging.info("Catch-up complete.")


# ------------------------------------------------------------------------------
# Graceful Exit Handler
# ------------------------------------------------------------------------------


def handle_exit(signum, frame):
    logging.info("Exiting gracefully...")
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    catch_up()
