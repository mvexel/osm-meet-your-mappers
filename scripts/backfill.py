#!/usr/bin/env python3
import datetime
import gzip
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple


def get_duplicate_ids(conn, cs_list: List[dict]) -> Set[int]:
    """
    Given a list of changeset dictionaries (each with an "id" key),
    return the set of IDs that already exist in the database.
    """
    cs_ids = [cs["id"] for cs in cs_list]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM changesets WHERE id = ANY(%s)", (cs_ids,))
        existing = cur.fetchall()
    return {row[0] for row in existing}


import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import yaml
from scripts.archive_loader import insert_batch, parse_changeset
from dotenv import load_dotenv
from lxml import etree

from osm_meet_your_mappers.db import get_db_connection

load_dotenv()

conn = get_db_connection()

# Global locks for insert and metadata updates.
insert_lock = threading.Lock()
metadata_lock = threading.Lock()

# Throttling globals
THROTTLE_DELAY = float(os.getenv("THROTTLE_DELAY", 1.0))  # seconds between requests
last_request_time = 0
throttle_lock = threading.Lock()


def throttle() -> None:
    """
    Ensures that each request is delayed by at least THROTTLE_DELAY seconds.
    """
    global last_request_time
    with throttle_lock:
        now = time.time()
        wait_time = THROTTLE_DELAY - (now - last_request_time)
        if wait_time > 0:
            time.sleep(wait_time)
        last_request_time = time.time()


def replication_file_url(
    seq_number: int,
    base_url: str = "https://planet.osm.org/replication/changesets",
) -> str:
    """
    Build the URL for the replication file corresponding to a given sequence number.
    """
    seq_str = f"{seq_number:09d}"
    dir1, dir2, file_part = seq_str[:3], seq_str[3:6], seq_str[6:]
    return f"{base_url}/{dir1}/{dir2}/{file_part}.osm.gz"


def download_and_decompress(url: str, req_session: requests.Session) -> bytes:
    logging.debug(f"Downloading {url}")
    response = req_session.get(url)
    response.raise_for_status()
    return gzip.decompress(response.content)


def download_with_retry(
    seq_number: int,
    req_session: requests.Session,
    retries: int = 3,
    initial_delay: float = 2.0,
) -> bytes:
    """
    Throttles before attempting a download.
    """
    url = replication_file_url(seq_number)
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
            throttle()  # Ensure we are not hammering OSM
            return download_and_decompress(url, req_session)
        except Exception as e:
            logging.error(f"Attempt {attempt} failed for sequence {seq_number}: {e}")
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
            else:
                logging.error(
                    f"All {retries} attempts failed for sequence {seq_number}"
                )
                raise


def get_current_sequence(
    state_url: str = "https://planet.osm.org/replication/changesets/state.yaml",
) -> int:
    """
    Retrieve the current replication sequence number from the state YAML file.
    """
    throttle()  # throttle even on state retrieval
    response = requests.get(state_url)
    response.raise_for_status()
    state = yaml.safe_load(response.text)
    sequence = int(state["sequence"])
    logging.debug(f"Current replication state sequence: {sequence}")
    return sequence


def upsert_changesets(
    conn, cs_batch: List[dict], tag_batch: List[dict], comment_batch: List[dict]
) -> None:
    """
    Upsert changesets into the database. If a changeset already exists, update it.
    """
    with conn.cursor() as cur:
        for cs in cs_batch:
            cur.execute(
                """
                INSERT INTO changesets (id, created_at, closed_at, open, user_id, user_name, num_changes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                closed_at = EXCLUDED.closed_at,
                open = EXCLUDED.open,
                num_changes = EXCLUDED.num_changes
                WHERE changesets.closed_at < EXCLUDED.closed_at OR changesets.open <> EXCLUDED.open;
            """,
                (
                    cs["id"],
                    cs["created_at"],
                    cs["closed_at"],
                    cs["open"],
                    cs["user_id"],
                    cs["user_name"],
                    cs["num_changes"],
                ),
            )

        for tag in tag_batch:
            cur.execute(
                """
                INSERT INTO changeset_tags (changeset_id, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (changeset_id, key) DO UPDATE SET
                value = EXCLUDED.value;
            """,
                (tag["changeset_id"], tag["key"], tag["value"]),
            )

        for comment in comment_batch:
            cur.execute(
                """
                INSERT INTO changeset_comments (changeset_id, user_id, user_name, date, text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (changeset_id, user_id, date) DO UPDATE SET
                text = EXCLUDED.text;
            """,
                (
                    comment["changeset_id"],
                    comment["user_id"],
                    comment["user_name"],
                    comment["date"],
                    comment["text"],
                ),
            )

    conn.commit()


def process_replication_content(
    xml_bytes: bytes, batch_size: int
) -> Tuple[bool, Optional[datetime.datetime]]:
    """
    Process the XML content of a replication file. Only closed changesets are processed.

    Returns:
      (file_empty, min_new_timestamp)
    """
    cs_batch: List[dict] = []
    tag_batch: List[dict] = []
    comment_batch: List[dict] = []
    processed = 0
    new_changesets_in_file = 0
    min_new_ts: Optional[datetime.datetime] = None

    stream = io.BytesIO(xml_bytes)
    context = etree.iterparse(stream, events=("end",), tag="changeset")
    for _, elem in context:
        parsed = parse_changeset(elem, None, None)
        if parsed:
            cs, tags, comments = parsed
            if not cs["open"]:
                cs_batch.append(cs)
                tag_batch.extend(tags)
                comment_batch.extend(comments)
            processed += 1
            if len(cs_batch) >= batch_size:
                with insert_lock:
                    dup_ids = get_duplicate_ids(conn, cs_batch)
                    new_cs_batch = [cs for cs in cs_batch if cs["id"] not in dup_ids]
                    new_tag_batch = [
                        tag for tag in tag_batch if tag["changeset_id"] not in dup_ids
                    ]
                    new_comment_batch = [
                        comment
                        for comment in comment_batch
                        if comment["changeset_id"] not in dup_ids
                    ]
                    if new_cs_batch:
                        batch_min = min(cs["created_at"] for cs in new_cs_batch)
                        if min_new_ts is None or batch_min < min_new_ts:
                            min_new_ts = batch_min
                        new_count = len(new_cs_batch)
                        most_recent_closed_at = max(
                            cs["created_at"] for cs in new_cs_batch
                        )
                        logging.info(
                            f"[{threading.current_thread().name}] Inserting {new_count} changesets, newest closed_at: {most_recent_closed_at}, id: {new_cs_batch[-1]['id']}"
                        )
                        upsert_changesets(
                            conn, new_cs_batch, new_tag_batch, new_comment_batch
                        )
                cs_batch.clear()
                tag_batch.clear()
                comment_batch.clear()

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    if cs_batch:
        with insert_lock:
            dup_ids = get_duplicate_ids(conn, cs_batch)
            new_cs_batch = [cs for cs in cs_batch if cs["id"] not in dup_ids]
            new_tag_batch = [
                tag for tag in tag_batch if tag["changeset_id"] not in dup_ids
            ]
            new_comment_batch = [
                comment
                for comment in comment_batch
                if comment["changeset_id"] not in dup_ids
            ]
            if new_cs_batch:
                batch_min = min(cs["created_at"] for cs in new_cs_batch)
                if min_new_ts is None or batch_min < min_new_ts:
                    min_new_ts = batch_min
                new_count = len(new_cs_batch)
                most_recent_closed_at = max(cs["created_at"] for cs in new_cs_batch)
                logging.info(
                    f"[{threading.current_thread().name}] Inserting {new_count} changesets, newest closed_at: {most_recent_closed_at}, id: {new_cs_batch[-1]['id']}"
                )
                insert_batch(conn, new_cs_batch, new_tag_batch, new_comment_batch)
    logging.debug(
        f"[{threading.current_thread().name}] Finished processing replication file: {processed} closed changesets parsed. New changesets: {new_changesets_in_file}"
    )
    file_empty = new_changesets_in_file == 0
    return file_empty, min_new_ts


def update_metadata(current_tip: int, last_processed: int) -> None:
    """
    Update the metadata table with the current tip and last processed sequence numbers.
    """
    with metadata_lock:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM metadata WHERE id = 1")
                row = cur.fetchone()
                now = datetime.datetime.now(datetime.UTC)
                if row is None:
                    cur.execute(
                        "INSERT INTO metadata (id, current_tip, last_processed, timestamp) VALUES (1, %s, %s, %s)",
                        (current_tip, last_processed, now),
                    )
                    logging.debug(
                        f"[{threading.current_thread().name}] Inserted metadata: current_tip={current_tip}, last_processed={last_processed}"
                    )
                else:
                    cur.execute(
                        "UPDATE metadata SET current_tip = %s, last_processed = %s, timestamp = %s WHERE id = 1",
                        (current_tip, last_processed, now),
                    )
                    logging.debug(
                        f"[{threading.current_thread().name}] Updated metadata: current_tip={current_tip}, last_processed={last_processed}"
                    )
                conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(
                f"[{threading.current_thread().name}] Failed to update metadata: {e}"
            )


def get_stored_metadata() -> Tuple[Optional[int], Optional[int]]:
    """
    Return the current tip and last processed sequence numbers from metadata.
    """
    with metadata_lock:
        with conn.cursor() as cur:
            cur.execute("SELECT current_tip, last_processed FROM metadata WHERE id = 1")
            row = cur.fetchone()
            return row if row else (None, None)


def wait_for_db(conn, max_retries=30, delay=1):
    """Wait for database to become available."""
    retries = 0
    while retries < max_retries:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception as e:
            logging.warning(
                f"Database connection failed (attempt {retries + 1}/{max_retries}): {e}"
            )
            time.sleep(delay)
            retries += 1
    return False


def process_block(
    block: List[int],
    req_session: requests.Session,
    batch_size: int,
    pool_name: str = "Pool",
) -> Tuple[bool, Optional[datetime.datetime]]:
    """
    Process a block (list) of sequence numbers concurrently.

    Returns:
      (all_duplicates, min_new_ts)

    'all_duplicates' is True if the entire block produced no new changesets.

    The 'pool_name' parameter is used to set the thread_name_prefix for the executor.
    """
    block_new_work = False
    min_ts: Optional[datetime.datetime] = None

    def process_single_file(s: int) -> Tuple[bool, Optional[datetime.datetime]]:
        try:
            throttle()
            xml_bytes = download_with_retry(
                s, req_session, retries=3, initial_delay=2.0
            )
            return process_replication_content(xml_bytes, batch_size)
        except Exception as e:
            logging.error(
                f"[{threading.current_thread().name}] Failed to process sequence {s}: {e}"
            )
            return True, None  # Treat as empty

    with ThreadPoolExecutor(
        max_workers=len(block), thread_name_prefix=pool_name
    ) as executor:
        futures = {executor.submit(process_single_file, s): s for s in block}
        for future in as_completed(futures):
            s = futures[future]
            try:
                file_empty, file_min_ts = future.result()
                if not file_empty:
                    block_new_work = True
                if file_min_ts is not None:
                    if min_ts is None or file_min_ts < min_ts:
                        min_ts = file_min_ts
            except Exception as e:
                logging.error(
                    f"[{threading.current_thread().name}] Error processing sequence {s}: {e}"
                )

    all_duplicates = not block_new_work
    return all_duplicates, min_ts


def backfill_worker(start_seq: int) -> None:
    """
    Worker that backfills from the stored oldest sequence down to START_SEQUENCE.
    """
    stored_tip, last_processed = get_stored_metadata()
    if stored_tip is None or last_processed is None:
        logging.info(
            f"[{threading.current_thread().name}] No stored metadata found, nothing to backfill."
        )
        return

    seq = last_processed
    block_size = int(os.getenv("BLOCK_SIZE", 10))
    batch_size = int(os.getenv("BATCH_SIZE", 1000))
    req_session = requests.Session()

    while seq > start_seq:
        block = list(range(seq, max(start_seq, seq - block_size) - 1, -1))
        logging.debug(
            f"[{threading.current_thread().name}] Processing block from {block[0]} down to {block[-1]}"
        )
        # Specify the pool name as "Backfill" so threads in this pool are clearly identified.
        _, _ = process_block(block, req_session, batch_size, pool_name="Backfill")
        seq = block[-1] - 1
        update_metadata(stored_tip, seq)
    logging.info(
        f"[{threading.current_thread().name}] Backfill worker reached START_SEQUENCE."
    )


def catch_up_worker() -> None:
    """
    Worker that polls for the current remote sequence and processes new changesets,
    filling gaps when necessary.
    """
    block_size = int(os.getenv("BLOCK_SIZE", 10))
    batch_size = int(os.getenv("BATCH_SIZE", 1000))
    req_session = requests.Session()

    while True:
        current_remote_seq = get_current_sequence()  # latest sequence OSM has
        stored_tip, last_processed = (
            get_stored_metadata()
        )  # latest sequence we have and last sequence processed by the catch up worker

        if stored_tip is None:
            stored_tip = current_remote_seq
            last_processed = current_remote_seq
            update_metadata(stored_tip, last_processed)

        logging.debug(
            f"[{threading.current_thread().name}] Current remote sequence: {current_remote_seq}, "
            f"Stored tip: {stored_tip}, Last processed: {last_processed}"
        )

        # Process new changesets if there are any
        if current_remote_seq > stored_tip:
            seq = current_remote_seq
            while seq > stored_tip:
                block = list(range(seq, max(stored_tip, seq - block_size), -1))
                logging.debug(
                    f"[{threading.current_thread().name}] Processing new block from {block[0]} down to {block[-1]}"
                )
                process_block(block, req_session, batch_size, pool_name="Catch-up")
                seq = block[-1] - 1
            update_metadata(current_remote_seq, seq)
            stored_tip, last_processed = current_remote_seq, seq

        # Fill gaps
        if last_processed < stored_tip:
            seq = stored_tip
            while seq > last_processed:
                block = list(range(seq, max(last_processed, seq - block_size), -1))
                logging.debug(
                    f"[{threading.current_thread().name}] Filling gap from {block[0]} down to {block[-1]}"
                )
                process_block(block, req_session, batch_size, pool_name="Gap-fill")
                seq = block[-1] - 1
            update_metadata(stored_tip, seq)

        logging.info(
            f"[{threading.current_thread().name}] Completed a pass. Sleeping before next poll..."
        )
        time.sleep(
            int(os.getenv("SLEEP_TIME", 300))
        )  # Sleep 5 minutes before checking again


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s]: %(message)s",
    )
    if not wait_for_db(conn):
        logging.error("Failed to connect to database after multiple attempts. Exiting.")
        return

    start_seq = int(os.getenv("START_SEQUENCE", 0))

    # If no metadata is stored yet, initialize it with the current remote sequence.
    stored_tip, last_processed = get_stored_metadata()
    if stored_tip is None or last_processed is None:
        current_seq = get_current_sequence()
        update_metadata(current_seq, current_seq)

    # Spawn the two worker threads with explicit names.
    t_backfill = threading.Thread(
        target=backfill_worker, args=(start_seq,), daemon=True, name="Backfill"
    )
    t_catchup = threading.Thread(target=catch_up_worker, daemon=True, name="Catch-up")

    t_backfill.start()
    t_catchup.start()

    t_backfill.join()
    t_catchup.join()

    logging.info("Both workers have exited. Main exiting.")


if __name__ == "__main__":
    main()
