#!/usr/bin/env python3
import gzip
import io
import logging
import signal
import sys
import threading
import time
import queue
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict

import requests
import yaml
from lxml import etree
from osm_meet_your_mappers.config import get_env_config, validate_config
from osm_meet_your_mappers.db import get_db_connection
from osm_meet_your_mappers.db_utils import upsert_changesets
from osm_meet_your_mappers.parsers import parse_changeset

# Load environment variables
config = get_env_config()
validate_config(config)

# Logging configuration
logging.basicConfig(
    level=config["log_level"],
    format="%(asctime)s %(levelname)s [%(threadName)s]: %(message)s",
)

THROTTLE_DELAY = float(config.get("throttle_delay", 1.0))
POLLING_INTERVAL = int(config.get("polling_interval", 60))  # seconds
MAX_WORKERS = int(config.get("max_workers", 4))
SEQUENCE_CHUNK_SIZE = int(config.get("sequence_chunk_size", 10))
MAX_DB_CONNECTIONS = int(config.get("max_db_connections", 16))
RETRY_INTERVAL = int(config.get("retry_interval", 300))  # seconds
MAX_RETRIES = int(config.get("max_retries", 3))

# Global state
running = True
sequence_lock = threading.Lock()
db_lock = threading.Lock()
stats_lock = threading.Lock()
stats = {
    "sequences_processed": 0,
    "changesets_inserted": 0,
    "errors": 0,
    "retries": 0,
}

# Failed sequences queue for retry
failed_sequences = queue.PriorityQueue()  # (retry_time, retry_count, seq_number)

# Database connection pool
db_pool_semaphore = threading.Semaphore(MAX_DB_CONNECTIONS)
db_pool_lock = threading.Lock()
db_pool = []


def get_db_connection_from_pool():
    """Get a database connection from the pool or create a new one."""
    conn = None

    # Try to get a connection from the pool
    with db_pool_lock:
        if db_pool:
            conn = db_pool.pop()

    # If no connection in pool, create a new one (with semaphore limiting)
    if conn is None:
        if not db_pool_semaphore.acquire(blocking=True, timeout=10.0):
            raise Exception(
                "Could not acquire database connection - too many connections"
            )
        try:
            conn = get_db_connection()
        except Exception as e:
            db_pool_semaphore.release()
            raise e

    return conn


def return_db_connection_to_pool(conn):
    """Return a database connection to the pool."""
    if conn is None or conn.closed:
        # If connection is closed, just release the semaphore
        db_pool_semaphore.release()
        return

    # Return connection to pool
    with db_pool_lock:
        db_pool.append(conn)


def signal_handler(sig, frame):
    global running
    logging.info("Received termination signal. Finishing current tasks and exiting...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def throttle() -> None:
    """Delay to avoid overwhelming OSM servers."""
    time.sleep(THROTTLE_DELAY)


def replication_file_url(seq_number: int) -> str:
    seq_str = f"{seq_number:09d}"
    dir1, dir2, file_part = seq_str[:3], seq_str[3:6], seq_str[6:]
    base_url = config.get(
        "replication_base_url", "https://planet.osm.org/replication/changesets"
    )
    return f"{base_url}/{dir1}/{dir2}/{file_part}.osm.gz"


def download_and_decompress(url: str) -> bytes:
    logging.debug(f"Downloading {url}")
    response = requests.get(url, allow_redirects=True)

    if response.status_code == 404:
        logging.warning(f"Replication file not found at {url}. Skipping.")
        raise FileNotFoundError

    response.raise_for_status()
    return gzip.decompress(response.content)


def update_sequence_status(
    seq_number: int, status: str, error_message: Optional[str] = None
) -> None:
    """Update the sequences table with the current status."""
    conn = None
    try:
        conn = get_db_connection_from_pool()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sequences (sequence_number, status, error_message)
                VALUES (%s, %s, %s)
                ON CONFLICT (sequence_number) DO UPDATE
                SET status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    ingested_at = NOW();
            """,
                (seq_number, status, error_message),
            )
            conn.commit()
    except Exception as e:
        logging.error(f"Failed to update sequence status: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            return_db_connection_to_pool(conn)


def update_stats(
    changesets_inserted: int = 0,
    sequences_processed: int = 0,
    errors: int = 0,
    retries: int = 0,
):
    """Thread-safe update of global statistics."""
    with stats_lock:
        stats["changesets_inserted"] += changesets_inserted
        stats["sequences_processed"] += sequences_processed
        stats["errors"] += errors
        stats["retries"] += retries


def process_replication_content(
    conn, xml_bytes: bytes, batch_size: int, cutoff_date: datetime
) -> Tuple[int, bool]:
    """Parse and insert changesets; stop if cutoff_date is reached."""
    stream = io.BytesIO(xml_bytes)
    context = etree.iterparse(stream, events=("end",), tag="changeset")

    # Parse all changesets first
    all_changesets = []
    for _, elem in context:
        cs = parse_changeset(elem)
        if cs:  # Include both open and closed changesets
            all_changesets.append(cs)

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    if not all_changesets:
        return 0, False

    # Check which changesets we already have and their metadata
    existing_data = {}
    with conn.cursor() as cur:
        cs_ids = [cs["id"] for cs in all_changesets]
        cur.execute(
            "SELECT id, closed_at, open, comments_count FROM changesets WHERE id = ANY(%s)",
            (cs_ids,),
        )
        existing_data = {
            row[0]: {"closed_at": row[1], "open": row[2], "comments_count": row[3]}
            for row in cur.fetchall()
        }

    # Process changesets
    cs_batch, inserted_count = [], 0
    all_old = True

    for cs in all_changesets:
        cs_id = cs["id"]
        closed_at = cs.get("closed_at")

        # Determine if this changeset should be processed
        should_process = True

        # If this changeset exists in our database
        if cs_id in existing_data:
            existing = existing_data[cs_id]

            # If existing is closed but new one is open, skip it
            if existing["closed_at"] and not closed_at:
                should_process = False

            # If existing has more comments than new one, skip it
            elif existing["comments_count"] > cs.get("comments_count", 0):
                should_process = False

        # Check cutoff date for closed changesets
        if closed_at and closed_at <= cutoff_date:
            # Only process if it's a new changeset or needs updating
            if should_process and cs_id not in existing_data:
                all_old = False
                cs_batch.append(cs)
        elif should_process:
            # Newer changeset or one that needs updating
            all_old = False
            cs_batch.append(cs)

        if len(cs_batch) >= batch_size:
            upsert_changesets(conn, cs_batch)
            inserted_count += len(cs_batch)
            cs_batch.clear()

    if cs_batch:
        upsert_changesets(conn, cs_batch)
        inserted_count += len(cs_batch)

    # Only stop if all changesets were old and we didn't need to update any
    reached_cutoff = all_old and len(all_changesets) > 0

    return inserted_count, reached_cutoff


def process_sequence(
    seq_number: int, batch_size: int, cutoff_date: datetime, retry_count: int = 0
) -> bool:
    """Process a single sequence; returns True if cutoff reached."""
    url = replication_file_url(seq_number)
    conn = None

    try:
        conn = get_db_connection_from_pool()
        update_sequence_status(seq_number, "processing")

        xml_bytes = download_and_decompress(url)
        inserted, reached_cutoff = process_replication_content(
            conn, xml_bytes, batch_size, cutoff_date
        )

        if reached_cutoff:
            update_sequence_status(seq_number, "backfilled")
            update_stats(changesets_inserted=inserted, sequences_processed=1)
            return True  # Stop backfill

        if inserted > 0:
            logging.info(f"Sequence {seq_number}: Processed {inserted} changesets.")
            update_sequence_status(seq_number, "backfilled")
        else:
            logging.info(f"Sequence {seq_number}: No new changesets.")
            update_sequence_status(seq_number, "empty")

        update_stats(changesets_inserted=inserted, sequences_processed=1)
        if retry_count > 0:
            update_stats(retries=1)

    except FileNotFoundError:
        logging.warning(f"Sequence {seq_number}: File not found. Marked as empty.")
        update_sequence_status(seq_number, "empty")
        update_stats(sequences_processed=1)
    except Exception as e:
        logging.error(f"Sequence {seq_number}: Failed with error: {e}")
        update_sequence_status(seq_number, "failed", error_message=str(e))
        update_stats(errors=1)

        # Add to retry queue if retries left
        if retry_count < MAX_RETRIES:
            retry_time = datetime.now() + timedelta(seconds=RETRY_INTERVAL)
            with sequence_lock:
                failed_sequences.put((retry_time, retry_count + 1, seq_number))
            logging.info(
                f"Sequence {seq_number} scheduled for retry ({retry_count + 1}/{MAX_RETRIES})"
            )
        else:
            logging.error(f"Sequence {seq_number} failed after {MAX_RETRIES} retries")

        return False
    finally:
        if conn:
            return_db_connection_to_pool(conn)

    return reached_cutoff


def get_current_sequence() -> int:
    """Fetch the current OSM sequence number from the replication state file."""
    url = config.get(
        "replication_state_url",
        "https://planet.osm.org/replication/changesets/state.yaml",
    )
    response = requests.get(url)
    response.raise_for_status()
    return int(yaml.safe_load(response.text)["sequence"])


def get_most_recent_closed_at() -> Optional[datetime]:
    """Get the most recent closed_at date from the changesets table."""
    conn = None
    try:
        conn = get_db_connection_from_pool()
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(closed_at) FROM changesets;")
            result = cur.fetchone()
            return result[0] if result and result[0] else None
    finally:
        if conn:
            return_db_connection_to_pool(conn)


def get_processed_sequences() -> Dict[int, str]:
    """Get all processed sequence numbers and their status."""
    conn = None
    try:
        conn = get_db_connection_from_pool()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sequence_number, status FROM sequences 
                WHERE status IN ('backfilled', 'empty');
                """
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        if conn:
            return_db_connection_to_pool(conn)


def get_failed_sequences() -> Dict[int, str]:
    """Get all failed sequence numbers and their error messages."""
    conn = None
    try:
        conn = get_db_connection_from_pool()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sequence_number, error_message FROM sequences 
                WHERE status = 'failed';
                """
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        if conn:
            return_db_connection_to_pool(conn)


def find_all_sequence_gaps(min_seq: int, max_seq: int) -> List[int]:
    """
    Find all gaps in sequences between min_seq and max_seq,
    including failed, processing, and missing sequences.
    """
    conn = None
    try:
        conn = get_db_connection_from_pool()
        with conn.cursor() as cur:
            # Get all sequences in our range
            cur.execute(
                """
                SELECT sequence_number, status FROM sequences 
                WHERE sequence_number BETWEEN %s AND %s;
                """,
                (min_seq, max_seq),
            )
            existing_seqs = {row[0]: row[1] for row in cur.fetchall()}

            # Find all missing or failed sequences
            all_seqs = set(range(min_seq, max_seq + 1))
            processed_seqs = {
                seq
                for seq, status in existing_seqs.items()
                if status in ("backfilled", "empty")
            }

            # Gaps include sequences that don't exist or failed
            gaps = all_seqs - processed_seqs

            # Log details about the gaps
            if gaps:
                failed = {
                    seq for seq, status in existing_seqs.items() if status == "failed"
                }
                processing = {
                    seq
                    for seq, status in existing_seqs.items()
                    if status == "processing"
                }
                missing = gaps - failed - processing

                logging.info(
                    f"Found {len(gaps)} gaps: {len(failed)} failed, "
                    f"{len(processing)} stuck in processing, {len(missing)} missing"
                )

            return sorted(gaps)
    finally:
        if conn:
            return_db_connection_to_pool(conn)


def check_and_fill_gaps(
    sequence_queue: queue.Queue, current_seq: int, highest_processed: int
) -> None:
    """Check for and fill any gaps in processed sequences."""
    if highest_processed <= 0 or current_seq <= 0:
        return

    # Find all gaps between current and highest processed
    min_seq = min(highest_processed, current_seq)
    max_seq = max(highest_processed, current_seq)
    gaps = find_all_sequence_gaps(min_seq, max_seq)

    if gaps:
        logging.info(
            f"Found {len(gaps)} gaps between sequences {min_seq} and {max_seq}. Adding to queue."
        )

        # Reset status for sequences stuck in 'processing'
        conn = None
        try:
            conn = get_db_connection_from_pool()
            with conn.cursor() as cur:
                # Find sequences stuck in processing for more than 10 minutes
                cur.execute(
                    """
                    UPDATE sequences 
                    SET status = 'failed', 
                        error_message = 'Reset after being stuck in processing'
                    WHERE status = 'processing' 
                    AND ingested_at < NOW() - INTERVAL '10 minutes'
                    AND sequence_number = ANY(%s)
                    RETURNING sequence_number;
                    """,
                    (list(gaps),),
                )
                reset_seqs = [row[0] for row in cur.fetchall()]
                if reset_seqs:
                    logging.info(
                        f"Reset {len(reset_seqs)} sequences stuck in 'processing' state"
                    )
                conn.commit()
        except Exception as e:
            logging.error(f"Error resetting stuck sequences: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                return_db_connection_to_pool(conn)

        # Add gaps to the queue in batches
        for i in range(0, len(gaps), SEQUENCE_CHUNK_SIZE):
            chunk = gaps[i : i + SEQUENCE_CHUNK_SIZE]
            for seq in chunk:
                sequence_queue.put(seq)


def retry_manager_thread(
    sequence_queue: queue.Queue, batch_size: int, cutoff_date: datetime
) -> None:
    """Thread to manage retrying failed sequences."""
    logging.info("Retry manager started")

    while running:
        try:
            # Check if there are sequences to retry
            now = datetime.now()
            while not failed_sequences.empty():
                # Peek at the next sequence
                retry_time, retry_count, seq_number = failed_sequences.queue[0]

                if retry_time <= now:
                    # Time to retry this sequence
                    failed_sequences.get()  # Remove from queue
                    logging.info(
                        f"Retrying sequence {seq_number} (attempt {retry_count}/{MAX_RETRIES})"
                    )

                    # Add to the main processing queue
                    sequence_queue.put((seq_number, retry_count))
                else:
                    # Not time to retry yet
                    break

            # Check for any failed sequences in the database that aren't in our retry queue
            if running and datetime.now().minute % 5 == 0:  # Check every 5 minutes
                failed_seqs = get_failed_sequences()
                if failed_seqs:
                    logging.info(
                        f"Found {len(failed_seqs)} failed sequences in database"
                    )

                    # Get sequences already in retry queue
                    retry_queue_seqs = set()
                    with sequence_lock:
                        for _, _, seq in list(failed_sequences.queue):
                            retry_queue_seqs.add(seq)

                    # Add sequences not already in retry queue
                    for seq in failed_seqs:
                        if seq not in retry_queue_seqs:
                            retry_time = datetime.now() + timedelta(
                                seconds=10
                            )  # Retry soon
                            with sequence_lock:
                                failed_sequences.put((retry_time, 1, seq))
                            logging.info(f"Added sequence {seq} to retry queue")

            # Sleep before checking again
            time.sleep(10)

        except Exception as e:
            logging.error(f"Error in retry manager: {e}")
            time.sleep(30)  # Wait before retrying


def worker_thread(
    sequence_queue: queue.Queue, batch_size: int, cutoff_date: datetime
) -> None:
    """Worker thread to process sequences from the queue."""
    thread_name = threading.current_thread().name
    logging.info(f"Worker {thread_name} started")

    while running:
        try:
            queue_item = sequence_queue.get(block=False)

            if queue_item is None:  # Sentinel value to stop
                sequence_queue.task_done()
                break

            # Unpack the queue item
            if isinstance(queue_item, tuple) and len(queue_item) == 2:
                seq_number, retry_count = queue_item
            else:
                seq_number, retry_count = queue_item, 0

            logging.debug(f"Worker {thread_name} processing sequence {seq_number}")
            reached_cutoff = process_sequence(
                seq_number, batch_size, cutoff_date, retry_count
            )
            sequence_queue.task_done()

            if reached_cutoff:
                with sequence_lock:
                    # Signal other threads to stop by adding sentinel values
                    for _ in range(MAX_WORKERS):
                        sequence_queue.put(None)
                break

        except queue.Empty:
            # No more sequences in queue, wait a bit
            time.sleep(0.1)
        except Exception as e:
            logging.error(f"Worker {thread_name} encountered error: {e}")
            update_stats(errors=1)
            if "queue_item" in locals():
                sequence_queue.task_done()


def backfill_changesets_mt(batch_size: int, cutoff_date: datetime) -> int:
    """
    Multi-threaded backfill of changesets from current sequence down to cutoff date.
    Returns the highest sequence processed.
    """
    current_seq = get_current_sequence()
    processed_seqs = get_processed_sequences()

    # Initialize sequences_to_process
    sequences_to_process = []
    highest_processed = 0
    lowest_processed = 0

    if processed_seqs:
        highest_processed = max(processed_seqs.keys())
        lowest_processed = min(processed_seqs.keys())

        # Check if we're already caught up
        if highest_processed >= current_seq:
            logging.info("Already up to date with the current sequence.")

            # Check for gaps in processed sequences
            gaps = find_all_sequence_gaps(lowest_processed, highest_processed)

            if not gaps:
                logging.info("No gaps detected in processed sequences.")
                return highest_processed
            else:
                logging.info(
                    f"Found {len(gaps)} gaps in processed sequences. Will fill them."
                )
                sequences_to_process = gaps
        else:
            # We have some processed sequences but need to process more
            logging.info(
                f"Continuing backfill from sequence {current_seq} down to {highest_processed+1}"
            )
            sequences_to_process = list(range(current_seq, highest_processed, -1))

            # Also check for gaps in already processed sequences
            gaps = find_all_sequence_gaps(lowest_processed, highest_processed)
            if gaps:
                logging.info(
                    f"Found {len(gaps)} gaps in previously processed sequences. Adding to queue."
                )
                sequences_to_process.extend(gaps)
    else:
        # No sequences processed yet, process all from current down
        logging.info(
            f"Starting backfill from sequence {current_seq} down to cutoff date {cutoff_date}"
        )
        sequences_to_process = list(range(current_seq, 0, -1))

    # If there's nothing to process, return current sequence
    if not sequences_to_process:
        logging.info("No sequences to process.")
        return current_seq

    # Create a queue of sequences to process
    sequence_queue = queue.Queue()

    # Add sequences to the queue in chunks to avoid memory issues
    for i in range(0, len(sequences_to_process), SEQUENCE_CHUNK_SIZE):
        chunk = sequences_to_process[i : i + SEQUENCE_CHUNK_SIZE]
        for seq in chunk:
            sequence_queue.put(seq)

    # Start the retry manager thread
    retry_thread = threading.Thread(
        target=retry_manager_thread,
        args=(sequence_queue, batch_size, cutoff_date),
        name="RetryManager",
    )
    retry_thread.daemon = True
    retry_thread.start()

    # Create and start worker threads
    workers = []
    for i in range(MAX_WORKERS):
        worker = threading.Thread(
            target=worker_thread,
            args=(sequence_queue, batch_size, cutoff_date),
            name=f"Worker-{i+1}",
        )
        worker.daemon = True
        worker.start()
        workers.append(worker)

    # Wait for all sequences to be processed
    sequence_queue.join()

    # Do one final gap check before finishing
    if highest_processed > 0 and lowest_processed > 0:
        # Check for gaps in the entire range we've processed
        min_seq = min(lowest_processed, min(sequences_to_process))
        max_seq = max(highest_processed, current_seq)

        final_queue = queue.Queue()
        gaps = find_all_sequence_gaps(min_seq, max_seq)

        if gaps:
            logging.info(f"Final check found {len(gaps)} gaps. Processing them...")

            # Add gaps to queue
            for seq in gaps:
                final_queue.put(seq)

            # Process any remaining gaps
            while not final_queue.empty():
                seq = final_queue.get()
                process_sequence(seq, batch_size, cutoff_date)
                final_queue.task_done()

    # Wait for all workers to finish
    for worker in workers:
        worker.join(timeout=1.0)

    # Log statistics
    logging.info(
        f"Backfill complete. Processed {stats['sequences_processed']} sequences, "
        f"inserted {stats['changesets_inserted']} changesets, "
        f"encountered {stats['errors']} errors, "
        f"performed {stats['retries']} retries."
    )

    # Return the current sequence as the highest processed
    return get_current_sequence()


def continuous_update_mt(batch_size: int, last_seq: int, cutoff_date: datetime) -> None:
    """Multi-threaded continuous update to process new sequences as they appear."""
    logging.info("Starting continuous update mode.")

    # Start the retry manager thread
    retry_queue = queue.Queue()
    retry_thread = threading.Thread(
        target=retry_manager_thread,
        args=(retry_queue, batch_size, cutoff_date),
        name="RetryManager",
    )
    retry_thread.daemon = True
    retry_thread.start()

    while running:
        try:
            current_seq = get_current_sequence()

            if current_seq > last_seq:
                logging.info(f"New sequences available: {last_seq+1} to {current_seq}")

                # Create a queue of new sequences to process
                sequence_queue = queue.Queue()
                for seq in range(last_seq + 1, current_seq + 1):
                    sequence_queue.put(seq)

                # Create and start worker threads
                workers = []
                for i in range(min(MAX_WORKERS, current_seq - last_seq)):
                    worker = threading.Thread(
                        target=worker_thread,
                        args=(sequence_queue, batch_size, cutoff_date),
                        name=f"Worker-{i+1}",
                    )
                    worker.daemon = True
                    worker.start()
                    workers.append(worker)

                # Wait for all sequences to be processed
                sequence_queue.join()

                # Wait for all workers to finish
                for worker in workers:
                    worker.join(timeout=1.0)

                last_seq = current_seq

                # Log statistics
                logging.info(
                    f"Update complete. Processed {stats['sequences_processed']} sequences, "
                    f"inserted {stats['changesets_inserted']} changesets, "
                    f"encountered {stats['errors']} errors, "
                    f"performed {stats['retries']} retries."
                )

                # Reset statistics for next update
                with stats_lock:
                    stats["sequences_processed"] = 0
                    stats["changesets_inserted"] = 0
                    stats["errors"] = 0
                    stats["retries"] = 0
            else:
                logging.debug(f"No new sequences available. Current: {current_seq}")

            # Wait before checking again
            for _ in range(POLLING_INTERVAL):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            logging.error(f"Error in continuous update: {e}")
            time.sleep(POLLING_INTERVAL)  # Wait before retrying


def main() -> None:
    batch_size = int(config.get("batch_size", 1000))
    cutoff_date = get_most_recent_closed_at()

    if not cutoff_date:
        logging.error(
            "No existing changesets found. Please use the archive loader first. We won't backfill the entire database."
        )
        sys.exit(1)

    logging.info(
        f"Starting with {MAX_WORKERS} worker threads and {MAX_DB_CONNECTIONS} database connections"
    )

    # First, backfill from current to cutoff date
    highest_seq = backfill_changesets_mt(batch_size, cutoff_date)

    # Then switch to continuous update mode
    if running:
        continuous_update_mt(batch_size, highest_seq, cutoff_date)

    logging.info("Process finished.")


if __name__ == "__main__":
    main()
