#!/usr/bin/env python3
import gzip
import io
import logging
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
import yaml
from lxml import etree

from osm_meet_your_mappers.config import get_env_config, validate_config
from osm_meet_your_mappers.db import get_db_connection
from osm_meet_your_mappers.db_utils import get_duplicate_ids, upsert_changesets
from osm_meet_your_mappers.parsers import parse_changeset

# Load environment variables
config = get_env_config()
validate_config(config)

# Logging configuration
logging.basicConfig(
    level=config["log_level"],
    format="%(asctime)s %(levelname)s: %(message)s",
)

THROTTLE_DELAY = float(config.get("throttle_delay", 1.0))
POLLING_INTERVAL = int(config.get("polling_interval", 60))  # seconds
running = True


def signal_handler(sig, frame):
    global running
    logging.info("Received termination signal. Finishing current task and exiting...")
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
    conn = get_db_connection()
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
    conn.close()


def insert_changeset_batch(cs_batch: List[dict]) -> int:
    """Insert a batch of changesets into the database."""
    if not cs_batch:
        return 0

    conn = get_db_connection()
    try:
        dup_ids = get_duplicate_ids(conn, cs_batch)
        new_cs_batch = [cs for cs in cs_batch if cs["id"] not in dup_ids]

        if not new_cs_batch:
            return 0

        for cs in new_cs_batch:
            if not cs.get("bbox") or cs["bbox"] in ("POINT(0 0)", ""):
                logging.warning(f"Changeset {cs['id']} has invalid geometry, skipping.")
                cs["bbox"] = None

        upsert_changesets(conn, new_cs_batch)
        logging.info(f"Inserted {len(new_cs_batch)} new changesets.")
        return len(new_cs_batch)
    finally:
        conn.close()


def get_most_recent_closed_at() -> Optional[datetime]:
    """Get the most recent closed_at date from the changesets table."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(closed_at) FROM changesets;")
            result = cur.fetchone()
            return result[0] if result and result[0] else None
    finally:
        conn.close()


def get_existing_changesets_info(changeset_ids: List[int]) -> Dict[int, int]:
    """Get existing changesets' IDs and comment counts."""
    if not changeset_ids:
        return {}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(changeset_ids))
            cur.execute(
                f"SELECT id, comments_count FROM changesets WHERE id IN ({placeholders})",
                changeset_ids,
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def process_replication_content(
    xml_bytes: bytes, batch_size: int, cutoff_date: datetime
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
    cs_ids = [cs["id"] for cs in all_changesets]
    existing_changesets = get_existing_changesets_metadata(cs_ids)

    # Process changesets
    cs_batch, inserted_count = [], 0
    all_old = True

    for cs in all_changesets:
        cs_id = cs["id"]
        closed_at = cs.get("closed_at")

        # Determine if this changeset should be processed
        should_process = False

        if cs_id not in existing_changesets:
            # New changeset, always process
            should_process = True
            all_old = False
        else:
            existing = existing_changesets[cs_id]

            # If the existing changeset is closed but this one is open,
            # this is an older version - skip it
            if existing.get("closed_at") and not closed_at:
                continue

            # If comment counts differ or tags differ, process it
            if existing.get("comments_count", 0) != cs.get(
                "comments_count", 0
            ) or existing.get("tags") != cs.get("tags"):
                should_process = True
                all_old = False

        # Check cutoff date for closed changesets
        if closed_at and closed_at <= cutoff_date:
            # Only process if it's a new changeset or needs updating
            if should_process:
                all_old = False
                cs_batch.append(cs)
        elif not closed_at and cs_id in existing_changesets:
            # Open changeset that we already have - skip
            continue
        else:
            # Newer changeset or open changeset we don't have yet
            all_old = False
            cs_batch.append(cs)

        if len(cs_batch) >= batch_size:
            inserted_count += insert_changeset_batch(cs_batch)
            cs_batch.clear()

    if cs_batch:
        inserted_count += insert_changeset_batch(cs_batch)

    # Only stop if all changesets were old and we didn't need to update any
    reached_cutoff = all_old and len(all_changesets) > 0

    return inserted_count, reached_cutoff


def get_existing_changesets_metadata(changeset_ids: List[int]) -> Dict[int, dict]:
    """Get existing changesets' metadata."""
    if not changeset_ids:
        return {}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(changeset_ids))
            cur.execute(
                f"""
                SELECT id, closed_at, comments_count, tags
                FROM changesets 
                WHERE id IN ({placeholders})
                """,
                changeset_ids,
            )
            return {
                row[0]: {"closed_at": row[1], "comments_count": row[2], "tags": row[3]}
                for row in cur.fetchall()
            }
    finally:
        conn.close()


def get_highest_processed_sequence() -> int:
    """Get the highest sequence number that was successfully processed."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(sequence_number) FROM sequences 
                WHERE status IN ('backfilled', 'empty');
                """
            )
            result = cur.fetchone()
            return result[0] if result and result[0] is not None else 0
    finally:
        conn.close()


def get_processed_sequences(min_seq: int, max_seq: int) -> Set[int]:
    """Get all sequence numbers in range that were successfully processed."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Only add range filter if both values are positive
            if min_seq > 0 and max_seq > 0:
                cur.execute(
                    """
                    SELECT sequence_number FROM sequences 
                    WHERE status IN ('backfilled', 'empty')
                    AND sequence_number BETWEEN %s AND %s;
                    """,
                    (min_seq, max_seq),
                )
            else:
                cur.execute(
                    """
                    SELECT sequence_number FROM sequences 
                    WHERE status IN ('backfilled', 'empty');
                    """
                )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def process_sequence(seq_number: int, batch_size: int, cutoff_date: datetime) -> bool:
    """Process a single sequence; returns True if cutoff reached."""
    url = replication_file_url(seq_number)
    update_sequence_status(seq_number, "processing")

    try:
        xml_bytes = download_and_decompress(url)
        inserted, reached_cutoff = process_replication_content(
            xml_bytes, batch_size, cutoff_date
        )

        if reached_cutoff:
            update_sequence_status(seq_number, "backfilled")
            return True  # Stop backfill

        if inserted > 0:
            logging.info(f"Sequence {seq_number}: Processed {inserted} changesets.")
            update_sequence_status(seq_number, "backfilled")
        else:
            logging.info(f"Sequence {seq_number}: No new changesets.")
            update_sequence_status(seq_number, "empty")

    except FileNotFoundError:
        logging.warning(f"Sequence {seq_number}: File not found. Marked as empty.")
        update_sequence_status(seq_number, "empty")
    except Exception as e:
        logging.error(f"Sequence {seq_number}: Failed with error: {e}")
        update_sequence_status(seq_number, "failed", error_message=str(e))
        return False

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


def backfill_changesets(batch_size: int, cutoff_date: datetime) -> int:
    """
    Backfill changesets from current sequence down to cutoff date.
    Ensures all gaps between processed sequences are filled.
    Returns the highest sequence processed.
    """
    current_seq = get_current_sequence()

    # Get all processed sequences
    processed_seqs = get_processed_sequences(0, current_seq)

    if processed_seqs:
        highest_processed = max(processed_seqs)
        lowest_processed = min(processed_seqs)

        # Check if we're already caught up
        if highest_processed >= current_seq:
            logging.info("Already up to date with the current sequence.")

            # Check for gaps in processed sequences
            if len(processed_seqs) == highest_processed - lowest_processed + 1:
                logging.info("No gaps detected in processed sequences.")
                return highest_processed
            else:
                logging.info("Gaps detected in processed sequences. Will fill them.")
    else:
        highest_processed = 0
        lowest_processed = 0

    # Start from current sequence if we haven't processed it yet
    start_seq = current_seq if current_seq not in processed_seqs else current_seq - 1

    logging.info(
        f"Starting backfill from sequence {start_seq} down to cutoff date {cutoff_date}"
    )

    # Process sequences until we reach the cutoff date
    seq = start_seq
    while seq > 0 and running:
        # Skip if already processed
        if seq in processed_seqs:
            seq -= 1
            continue

        # Process this sequence
        if process_sequence(seq, batch_size, cutoff_date):
            logging.info("Cutoff date reached. Backfill complete.")
            break

        throttle()
        seq -= 1

    # After backfill, check for any remaining gaps
    processed_seqs = get_processed_sequences(0, current_seq)
    gaps = find_sequence_gaps(processed_seqs, current_seq)

    if gaps:
        logging.info(f"Found {len(gaps)} gaps in processed sequences. Filling gaps...")
        for gap_seq in gaps:
            if not running:
                break
            process_sequence(gap_seq, batch_size, cutoff_date)
            throttle()

    return get_current_sequence()  # Return the latest sequence


def find_sequence_gaps(processed_seqs: Set[int], max_seq: int) -> List[int]:
    """Find gaps in processed sequences up to max_seq."""
    if not processed_seqs:
        return list(range(1, max_seq + 1))

    # Find the minimum sequence we've processed
    min_seq = min(processed_seqs)

    # We only care about gaps between min_seq and max_seq
    expected_seqs = set(range(min_seq, max_seq + 1))

    # Find sequences that should be processed but aren't
    return sorted(expected_seqs - processed_seqs)


def continuous_update(batch_size: int, last_seq: int, cutoff_date: datetime) -> None:
    """Continuously check for and process new sequences."""
    logging.info("Starting continuous update mode.")

    while running:
        try:
            current_seq = get_current_sequence()

            if current_seq > last_seq:
                logging.info(f"New sequences available: {last_seq+1} to {current_seq}")

                # Process new sequences in forward order
                for seq in range(last_seq + 1, current_seq + 1):
                    if not running:
                        break

                    process_sequence(seq, batch_size, cutoff_date)
                    throttle()

                last_seq = current_seq
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

    # First, backfill from current to cutoff date
    highest_seq = backfill_changesets(batch_size, cutoff_date)

    # Then switch to continuous update mode
    if running:
        continuous_update(batch_size, highest_seq, cutoff_date)

    logging.info("Process finished.")


if __name__ == "__main__":
    main()
