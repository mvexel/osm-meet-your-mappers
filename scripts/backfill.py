#!/usr/bin/env python3
import datetime
import gzip
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Optional, Set, Tuple

import requests
import yaml
from archive_loader import insert_batch, parse_changeset
from dotenv import load_dotenv
from lxml import etree

from osm_meet_your_mappers.db import get_db_connection

load_dotenv()

conn = get_db_connection()

insert_lock = threading.Lock()
metadata_lock = threading.Lock()


def get_highest_missing_id(conn):
    """
    Find the highest changeset ID that is missing - this may be a gap or the bottom
    of where we have replicated.
    We don't use this yet....
    """
    query = """
    WITH m AS (
      SELECT MIN(id) AS min_id, MAX(id) AS max_id
      FROM changesets
    ),
    candidate_ids AS (
      -- Candidate below the current min:
      SELECT (min_id - 1) AS candidate
      FROM m
      UNION
      -- Candidates for gaps between IDs:
      SELECT t1.id + 1
      FROM changesets t1
      UNION
      -- Candidate after the current max (in case there are no gaps):
      SELECT (max_id + 1)
      FROM m
    )
    SELECT candidate AS highest_missing_id
    FROM candidate_ids c
    WHERE candidate >= 0
      AND NOT EXISTS (SELECT 1 FROM changesets WHERE id = candidate)
    ORDER BY candidate
    LIMIT 1;
    """
    with conn.cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()
        return result[0] if result is not None else None


def replication_file_url(
    seq_number: int, base_url: str = "https://planet.osm.org/replication/changesets"
) -> str:
    """
    Build the URL for the replication file corresponding to a given sequence number.
    The sequence number is padded to 9 digits and split into three parts.
    For example, sequence 6387144 becomes:
      "006387144" → URL: /006/387/144.osm.gz
    """
    seq_str = f"{seq_number:09d}"
    dir1, dir2, file_part = seq_str[:3], seq_str[3:6], seq_str[6:]
    return f"{base_url}/{dir1}/{dir2}/{file_part}.osm.gz"


def download_and_decompress(url: str, req_session: requests.Session) -> bytes:
    """
    Download a gzipped file from the given URL and return its decompressed bytes.
    """
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
    Attempt to download and decompress the replication file corresponding to the given sequence number.
    Uses exponential backoff. Raises an exception if all attempts fail.
    """
    url = replication_file_url(seq_number)
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
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
    response = requests.get(state_url)
    response.raise_for_status()
    state = yaml.safe_load(response.text)
    sequence = int(state["sequence"])
    logging.debug(f"Current replication state sequence: {sequence}")
    return sequence


def get_duplicate_ids(conn, cs_list: List[dict]) -> Set[int]:
    """
    Given a list of changeset dictionaries (each with an "id" key), return the set of IDs that
    already exist in the database.
    """
    cs_ids = [cs["id"] for cs in cs_list]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM changesets WHERE id = ANY(%s)", (cs_ids,))
        existing = cur.fetchall()
    return {row[0] for row in existing}


def process_replication_content(
    xml_bytes: bytes, batch_size: int
) -> Tuple[bool, Optional[datetime.datetime]]:
    """
    Process the XML content (bytes) of a replication file using a streaming parser.

    Only closed changesets (where cs_obj.open is False) are processed. The function accumulates
    batches of changesets and, under a global lock, queries for duplicates and inserts only new ones.

    Returns a tuple:
        (file_empty, min_new_timestamp)
      - file_empty: True if the replication file produced zero new changesets.
      - min_new_timestamp: The oldest 'created_at' timestamp among new changesets inserted in this file, or None.
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
        # Parse changeset XML directly without ORM
        parsed = parse_changeset(elem, None, None)
        if parsed:
            cs, tags, comments = parsed
            if not cs["open"]:  # only process closed changesets
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
                        new_changesets_in_file += new_count
                        logging.debug(
                            f"Inserting batch of {new_count} new changesets (from {len(cs_batch)} closed changesets)"
                        )
                        insert_batch(
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
                new_changesets_in_file += new_count
                logging.info(
                    f"Inserting final batch of {new_count} new changesets (from {len(cs_batch)} closed changesets)"
                )
                insert_batch(conn, new_cs_batch, new_tag_batch, new_comment_batch)
    logging.debug(
        f"Finished processing replication file: {processed} closed changesets parsed. New changesets: {new_changesets_in_file}"
    )
    file_empty = new_changesets_in_file == 0
    return file_empty, min_new_ts


def update_metadata_state(new_ts: datetime.datetime) -> None:
    """
    Update the Metadata table (row with id==1) so that its state field reflects the oldest changeset timestamp.
    For backwards replication, update only if the new timestamp is older than the current state.
    This operation is serialized using a global lock.
    """
    with metadata_lock:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT state FROM metadata WHERE id = 1")
                row = cur.fetchone()
                now = datetime.datetime.now(datetime.UTC)
                if row is None:
                    cur.execute(
                        "INSERT INTO metadata (id, state, timestamp) VALUES (1, %s, %s)",
                        (new_ts.isoformat(), now),
                    )
                    logging.debug(f"Inserted metadata state: {new_ts.isoformat()}")
                else:
                    current_state_ts = datetime.datetime.fromisoformat(row[0])
                    if new_ts < current_state_ts:
                        cur.execute(
                            "UPDATE metadata SET state = %s, timestamp = %s WHERE id = 1",
                            (new_ts.isoformat(), now),
                        )
                        logging.debug(
                            f"Updated metadata state from {row[0]} to {new_ts.isoformat()}"
                        )
                conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(
                f"Failed to update metadata state for timestamp {new_ts.isoformat()}: {e}"
            )


def wait_for_db(conn, max_retries=30, delay=1):
    """Wait for database to become available"""
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


def main() -> None:

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )

    # Wait for database to become available
    if not wait_for_db(conn):
        logging.error("Failed to connect to database after multiple attempts. Exiting.")
        return
    req_session = requests.Session()

    start_seq = int(os.getenv("START_SEQUENCE", 0))
    current_seq = get_current_sequence()

    if start_seq > current_seq:
        logging.error("START_SEQUENCE is greater than the current sequence. Exiting.")
        return

    seq = start_seq
    while seq <= current_seq:
        # Build a block of sequence numbers (in ascending order).
        block = list(
            range(
                seq,
                min(
                    current_seq + 1,
                    seq + int(os.getenv("BLOCK_SIZE", 10)),
                ),
            )
        )

        block_new_work = False

        def process_single_file(s: int) -> Tuple[bool, Optional[datetime.datetime]]:
            try:
                xml_bytes = download_with_retry(
                    s, req_session, retries=3, initial_delay=2.0
                )
                return process_replication_content(
                    xml_bytes, int(os.getenv("BATCH_SIZE", 1000))
                )
            except Exception as e:
                logging.error(f"Failed to process sequence {s}: {e}")
                return True, None

            with ThreadPoolExecutor(
                max_workers=int(os.getenv("BLOCK_SIZE", 10))
            ) as executor:
                futures = {executor.submit(process_single_file, s): s for s in block}
                for future in as_completed(futures):
                    s = futures[future]
                    try:
                        file_empty, min_new_ts = future.result()
                        if min_new_ts is not None:
                            update_metadata_state(min_new_ts, conn)
                        if not file_empty:
                            block_new_work = True
                    except Exception as e:
                        logging.error(f"Error processing sequence {s}: {e}")

            if block_new_work:
                work_done_overall = True

            # Update seq to the smallest sequence in this block minus one.
            seq = min(block) - 1

        # If the entire block produced no new changesets, assume we've caught up.
        if not block_new_work:
            logging.info(
                "No new changesets found in this block; stopping processing."
            )
            break

        # Update seq to the largest sequence in this block plus one.
        seq = max(block) + 1

    logging.info("Finished processing all available sequences.")


if __name__ == "__main__":
    main()
