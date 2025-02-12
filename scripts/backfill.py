#!/usr/bin/env python3
import argparse
import gzip
import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, List, Optional, Set, Tuple

import requests
import yaml
from lxml import etree
from osm_meet_your_mappers.db import create_engine  # your engine setup
from osm_meet_your_mappers.model import Changeset, Metadata
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker  # type: ignore
from sqlalchemy.pool import QueuePool
from archive_loader import insert_batch

# Global locks to serialize duplicate checking/insertion and metadata updates.
insert_lock = threading.Lock()
metadata_lock = threading.Lock()


def model_to_dict(instance) -> dict:
    """
    Convert a SQLAlchemy model instance to a dictionary for bulk insertion.
    Only includes the columns defined in the model's table.
    For geometry columns (like bbox) the value is converted to EWKT.
    """
    from geoalchemy2.shape import to_shape

    d = {}
    for col in instance.__table__.columns:
        value = getattr(instance, col.name)
        if col.name == "bbox" and value is not None:
            d[col.name] = f"SRID=4326;{to_shape(value).wkt}"
        else:
            d[col.name] = value
    return d


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
    logging.info(f"Downloading {url}")
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
    logging.info(f"Current replication state sequence: {sequence}")
    return sequence


def get_duplicate_ids(SessionMaker: Any, cs_list: List[dict]) -> Set[int]:
    """
    Given a list of changeset dictionaries (each with an "id" key), return the set of IDs that
    already exist in the database.
    """
    cs_ids = [cs["id"] for cs in cs_list]
    session = SessionMaker()
    try:
        existing = (
            session.execute(select(Changeset.id).where(Changeset.id.in_(cs_ids)))
            .scalars()
            .all()
        )
        return set(existing)
    finally:
        session.close()


def process_replication_content(
    xml_bytes: bytes, SessionMaker: Any, batch_size: int
) -> Tuple[bool, Optional[datetime]]:
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
    min_new_ts: Optional[datetime] = None

    stream = io.BytesIO(xml_bytes)
    context = etree.iterparse(stream, events=("end",), tag="changeset")
    for _, elem in context:
        cs_obj = Changeset.from_xml(elem)
        if cs_obj and not cs_obj.open:  # only process closed changesets
            cs_dict = model_to_dict(cs_obj)
            cs_batch.append(cs_dict)
            tag_batch.extend([model_to_dict(tag) for tag in cs_obj.tags])
            comment_batch.extend(
                [model_to_dict(comment) for comment in cs_obj.comments]
            )
            processed += 1

            if len(cs_batch) >= batch_size:
                with insert_lock:
                    dup_ids = get_duplicate_ids(SessionMaker, cs_batch)
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
                            f"Inserting batch of {new_count} new changesets (from {len(cs_batch)} closed changesets)"
                        )
                        insert_batch(
                            SessionMaker, new_cs_batch, new_tag_batch, new_comment_batch
                        )
                cs_batch.clear()
                tag_batch.clear()
                comment_batch.clear()

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    if cs_batch:
        with insert_lock:
            dup_ids = get_duplicate_ids(SessionMaker, cs_batch)
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
                insert_batch(
                    SessionMaker, new_cs_batch, new_tag_batch, new_comment_batch
                )
    logging.info(
        f"Finished processing replication file: {processed} closed changesets parsed. New changesets: {new_changesets_in_file}"
    )
    file_empty = new_changesets_in_file == 0
    return file_empty, min_new_ts


def update_metadata_state(new_ts: datetime, SessionMaker: Any) -> None:
    """
    Update the Metadata table (row with id==1) so that its state field reflects the oldest changeset timestamp.
    For backwards replication, update only if the new timestamp is older than the current state.
    This operation is serialized using a global lock.
    """
    with metadata_lock:
        session = SessionMaker()
        try:
            row = session.query(Metadata).filter(Metadata.id == 1).first()
            now = datetime.utcnow()
            if row is None:
                # Explicitly set the id to 1 so that we update the same row in future calls.
                row = Metadata(id=1, state=new_ts.isoformat(), timestamp=now)
                session.add(row)
                logging.info(f"Inserted metadata state: {new_ts.isoformat()}")
            else:
                try:
                    current_state_ts = datetime.fromisoformat(row.state)
                except Exception:
                    current_state_ts = None
                # For backwards replication, update only if the new timestamp is older.
                if current_state_ts is None or new_ts < current_state_ts:
                    old_state = row.state
                    row.state = new_ts.isoformat()
                    row.timestamp = now
                    logging.info(
                        f"Updated metadata state from {old_state} to {new_ts.isoformat()}"
                    )
            session.commit()
        except Exception as e:
            session.rollback()
            logging.error(
                f"Failed to update metadata state for timestamp {new_ts.isoformat()}: {e}"
            )
        finally:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously backfill the changeset database from OSM replication files (backwards replication) using multithreading, updating metadata state with the oldest changeset timestamp."
    )
    parser.add_argument(
        "db_url", help="SQLAlchemy database URL (e.g. postgresql://user:pass@host/db)"
    )
    parser.add_argument(
        "--min-seq",
        type=int,
        default=0,
        help="Minimum replication sequence number to stop backfilling (default: 0)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50000,
        help="Batch size for bulk inserts (default: 50000)",
    )
    parser.add_argument(
        "--block-size",
        type=int,
        default=10,
        help="Number of replication files to process concurrently (default: 10)",
    )
    parser.add_argument(
        "--sleep-time",
        type=int,
        default=300,
        help="Time (in seconds) to sleep when no new work is found (default: 300 seconds)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )

    engine = create_engine(
        args.db_url,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_pre_ping=True,
    )
    SessionMaker = sessionmaker(bind=engine)
    req_session = requests.Session()

    while True:
        try:
            current_seq = get_current_sequence()
        except Exception as e:
            logging.error(f"Failed to fetch current replication sequence: {e}")
            time.sleep(args.sleep_time)
            continue

        work_done_overall = False
        seq = current_seq
        # Process replication files in descending order until we reach --min-seq.
        while seq > args.min_seq:
            # Build a block of sequence numbers (in descending order).
            block = list(range(seq, max(args.min_seq, seq - args.block_size) - 1, -1))
            if not block:
                break

            block_new_work = False

            def process_single_file(s: int) -> Tuple[bool, Optional[datetime]]:
                try:
                    xml_bytes = download_with_retry(
                        s, req_session, retries=3, initial_delay=2.0
                    )
                    return process_replication_content(
                        xml_bytes, SessionMaker, args.batch_size
                    )
                except Exception as e:
                    logging.error(f"Failed to process sequence {s}: {e}")
                    return True, None

            with ThreadPoolExecutor(max_workers=args.block_size) as executor:
                futures = {executor.submit(process_single_file, s): s for s in block}
                for future in as_completed(futures):
                    s = futures[future]
                    try:
                        file_empty, min_new_ts = future.result()
                        if min_new_ts is not None:
                            update_metadata_state(min_new_ts, SessionMaker)
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
                    "No new changesets found in this block; stopping backward processing."
                )
                break

        if not work_done_overall:
            logging.info(
                f"No new replication work found. Sleeping for {args.sleep_time} seconds..."
            )
            time.sleep(args.sleep_time)
        else:
            logging.info(
                "Finished processing current backfill block. Checking for more work shortly..."
            )
            time.sleep(30)


if __name__ == "__main__":
    main()
