import logging
import queue
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import get_db_session, get_last_processed_sequence
from osm_changeset_loader.model import Changeset
from osm_changeset_loader.path import Path
from osm_changeset_loader.replication import ReplicationClient

# Configuration
config = Config()
replication_client = ReplicationClient(config)

# Number of threads for processing
THREADS = 8
CHUNK_SIZE = 1000  # Number of sequences per chunk

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


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


def insert_changesets_bulk(changesets) -> bool:
    """Bulk insert or update changesets to optimize database performance."""
    try:
        with session_scope() as session:
            for cs in changesets:
                session.merge(cs)
        return True
    except Exception as e:
        logging.error(f"Error inserting changesets: {e}")
        return False


def process_sequence(sequence: int) -> bool:
    """Process a single replication sequence."""
    try:
        current_path = Path(sequence=sequence)
        logging.info(f"Processing sequence {sequence}")
        changesets = replication_client.get_changesets(current_path)
        if changesets:
            return insert_changesets_bulk(changesets)
    except Exception as e:
        logging.error(f"Error processing sequence {sequence}: {e}")
    return False


def worker(stop_event: threading.Event, task_queue: queue.Queue):
    """Process changesets using a task queue."""
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
            time.sleep(0.1)  # Rate limiting

        task_queue.task_done()


def load_historical(start_sequence: int, end_sequence: int, continuous: bool = False):
    """
    Load historical changesets from start_sequence to end_sequence with continuous updates.

    Args:
        start_sequence: Starting sequence number
        end_sequence: Ending sequence number
        continuous: Whether to keep running and check for new sequences
    """
    stop_event = threading.Event()
    last_processed = start_sequence

    # If no sequence range specified, use last processed from metadata
    if start_sequence == 0 and end_sequence == 0:
        start_sequence = get_last_processed_sequence() + 1
        end_sequence = replication_client.get_remote_state().sequence

    # Signal handlers for graceful exit
    signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())
    signal.signal(signal.SIGINT, lambda s, f: stop_event.set())

    # Build task queue
    task_queue = queue.Queue()
    current = start_sequence
    while current <= end_sequence:
        chunk_end = min(end_sequence, current + CHUNK_SIZE - 1)
        task_queue.put((current, chunk_end))
        current = chunk_end + 1

    # Process chunks using thread pool
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [
            executor.submit(worker, stop_event, task_queue) for _ in range(THREADS)
        ]

        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            logging.info("Interrupted! Stopping processing.")
            stop_event.set()

    logging.info("Historical load complete.")
    
    if continuous:
        logging.info("Entering continuous update mode...")
        while not stop_event.is_set():
            try:
                current_remote = replication_client.get_remote_state().sequence
                if current_remote > end_sequence:
                    logging.info(f"New sequences available: {end_sequence+1}-{current_remote}")
                    load_historical(end_sequence + 1, current_remote)
                    end_sequence = current_remote
                time.sleep(60)  # Check every minute
            except Exception as e:
                logging.error(f"Error in continuous mode: {e}")
                time.sleep(30)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load historical OSM changesets")
    parser.add_argument("--continuous", action="store_true", 
                      help="Run in continuous mode checking for new changesets")
    parser.add_argument("start", type=int, nargs='?', default=0,
                      help="Starting sequence number (default: last processed)")
    parser.add_argument("end", type=int, nargs='?', default=0,
                      help="Ending sequence number (default: current remote state)")

    args = parser.parse_args()
    load_historical(args.start, args.end, args.continuous)
