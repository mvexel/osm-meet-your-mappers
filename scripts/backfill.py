#!/usr/bin/env python3
import gzip
import io
import logging
import sys
import time
from datetime import datetime
from typing import Optional, Tuple, List

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


def process_replication_content(
    xml_bytes: bytes, batch_size: int, cutoff_date: datetime
) -> Tuple[int, bool]:
    """Parse and insert changesets; stop if cutoff_date is reached."""
    cs_batch, inserted_count, reached_cutoff = [], 0, False
    stream = io.BytesIO(xml_bytes)
    context = etree.iterparse(stream, events=("end",), tag="changeset")

    for _, elem in context:
        cs = parse_changeset(elem)
        if cs and not cs["open"]:
            closed_at = (
                datetime.fromisoformat(cs["closed_at"]) if cs["closed_at"] else None
            )

            if closed_at and closed_at <= cutoff_date:
                logging.info(f"Reached cutoff date: {closed_at}. Stopping backfill.")
                reached_cutoff = True
                break

            cs_batch.append(cs)
            if len(cs_batch) >= batch_size:
                inserted_count += insert_changeset_batch(cs_batch)
                cs_batch.clear()

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    if cs_batch and not reached_cutoff:
        inserted_count += insert_changeset_batch(cs_batch)

    return inserted_count, reached_cutoff


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
            logging.info(f"Sequence {seq_number}: Backfilled {inserted} changesets.")
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

    return False  # Continue backfill


def get_current_sequence() -> int:
    """Fetch the current OSM sequence number from the replication state file."""
    url = config.get(
        "replication_state_url",
        "https://planet.osm.org/replication/changesets/state.yaml",
    )
    response = requests.get(url)
    response.raise_for_status()
    return int(yaml.safe_load(response.text)["sequence"])


def main() -> None:
    batch_size = int(config.get("batch_size", 1000))
    start_seq = get_current_sequence()
    cutoff_date = get_most_recent_closed_at()

    if not cutoff_date:
        logging.error("No existing changesets found. Provide a valid cutoff date.")
        sys.exit(1)

    logging.info(
        f"Starting backfill from sequence {start_seq} down to cutoff date {cutoff_date}"
    )

    for seq in range(start_seq, -1, -1):
        if process_sequence(seq, batch_size, cutoff_date):
            logging.info("Cutoff date reached. Backfill complete.")
            break
        throttle()

    logging.info("Backfill process finished.")


if __name__ == "__main__":
    main()
