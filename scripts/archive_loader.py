#!/usr/bin/env python3
import argparse
import bz2
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

from lxml import etree
from osm_meet_your_mappers.db import create_tables
from osm_meet_your_mappers.model import Changeset, ChangesetComment, ChangesetTag
from shapely.geometry import box
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from truncate_db import truncate_tables

BATCH_SIZE = 50_000
NUM_WORKERS = 4
POOL_SIZE = 10  # database connection pool size


def valid_yyyymmdd(date_str):
    try:
        if len(date_str) != 8 or not date_str.isdigit():
            raise ValueError
        datetime.strptime(date_str, "%Y%m%d")
        return date_str
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {date_str}. Expected YYYYMMDD."
        )


def parse_datetime(dt_str):
    """
    Parse an ISO datetime string.
    The OSM timestamps have a trailing 'Z' to indicate UTC.
    """
    if not dt_str:
        return None
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(dt_str)
    except Exception as ex:
        logging.warning(f"Failed to parse datetime {dt_str}: {ex}")
        return None


def parse_changeset(
    elem: etree._Element, from_date: Optional[date], to_date=Optional[date]
):
    """
    Given an lxml element representing a <changeset>, extract a tuple:
       (changeset_dict, list_of_tags, list_of_comments)
    """
    try:
        cs_id = int(elem.attrib.get("id", "0"))
        if cs_id <= 0:
            return None
    except ValueError:
        return None

    created_at = parse_datetime(elem.attrib.get("created_at"))
    if created_at is None:
        return None  # Invalid datetime, skip

    # Apply date filtering early
    if from_date and created_at.date() < from_date:
        return None
    if to_date and created_at.date() > to_date:
        return None

    cs = {
        "id": cs_id,
        "user": elem.attrib.get("user"),
        "uid": int(elem.attrib.get("uid", 0)),
        "created_at": created_at,
        "closed_at": parse_datetime(elem.attrib.get("closed_at")),
        "open": elem.attrib.get("open", "").lower() == "true",
        "num_changes": int(elem.attrib.get("num_changes", 0)),
        "comments_count": int(elem.attrib.get("comments_count", 0)),
        "min_lat": float(elem.attrib.get("min_lat", 0)),
        "min_lon": float(elem.attrib.get("min_lon", 0)),
        "max_lat": float(elem.attrib.get("max_lat", 0)),
        "max_lon": float(elem.attrib.get("max_lon", 0)),
    }

    # Add the new bbox field in EWKT format
    cs["bbox"] = (
        f"SRID=4326;{box(cs['min_lon'], cs['min_lat'], cs['max_lon'], cs['max_lat']).wkt}"
    )

    # Parse tags.
    tags = [
        {
            "changeset_id": cs_id,
            "k": tag.attrib["k"],
            "v": tag.attrib.get("v"),
        }
        for tag in elem.findall("tag")
    ]

    # Parse discussion comments if any.
    comments = []
    discussion = elem.find("discussion")
    if discussion is not None:
        for comment in discussion.findall("comment"):
            comments.append(
                {
                    "changeset_id": cs_id,
                    "uid": int(comment.attrib.get("uid", 0)),
                    "user": comment.attrib.get("user"),
                    "date": parse_datetime(comment.attrib.get("date")),
                    "text": comment.findtext("text"),
                }
            )

    return cs, tags, comments


@contextmanager
def disable_foreign_keys(session):
    """Temporarily disable foreign key checks for faster bulk inserts."""
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    try:
        yield
    finally:
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def insert_batch(Session, cs_batch, tag_batch, comment_batch):
    """
    Insert a batch of data using a newly created session.
    Each worker gets its own session from the Session factory.
    """
    session = Session()
    try:
        with disable_foreign_keys(session):
            if cs_batch:
                session.bulk_insert_mappings(Changeset, cs_batch)
            if tag_batch:
                session.bulk_insert_mappings(ChangesetTag, tag_batch)
            if comment_batch:
                session.bulk_insert_mappings(ChangesetComment, comment_batch)
            session.commit()
    except Exception as ex:
        session.rollback()
        logging.error("Error during batch insert: %s", ex)
        raise
    finally:
        session.close()


def process_changeset_file(
    filename, Session, from_date, to_date, batch_size=BATCH_SIZE
):
    """
    Process the main .osm.bz file containing changesets, tags, and discussion comments.
    Batches of parsed records are handed off to worker threads,
    each of which gets its own session.
    """
    cs_batch = []
    tag_batch = []
    comment_batch = []
    processed = 0
    batch_counter = 0

    with bz2.open(filename, "rb") as f:
        context = etree.iterparse(f, events=("end",), tag="changeset")
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = []
            for _, elem in context:
                parsed = parse_changeset(elem, from_date, to_date)
                if parsed:
                    cs, tags, comments = parsed
                    cs_batch.append(cs)
                    tag_batch.extend(tags)
                    comment_batch.extend(comments)
                    processed += 1

                    if processed % batch_size == 0:
                        batch_counter += 1
                        min_created_at = min([cs["created_at"] for cs in cs_batch])
                        logging.info(
                            f"Queueing batch #{batch_counter} with {len(cs_batch)} changesets, starting at {min_created_at}"
                        )
                        # Submit the batch for processing.
                        futures.append(
                            executor.submit(
                                insert_batch,
                                Session,
                                cs_batch.copy(),
                                tag_batch.copy(),
                                comment_batch.copy(),
                            )
                        )
                        cs_batch.clear()
                        tag_batch.clear()
                        comment_batch.clear()

                # Free memory.
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]

            # Wait for all batches to complete.
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"Error processing batch: {e}")

    # Insert any remaining rows.
    if cs_batch:
        logging.info("Inserting final batch")
        insert_batch(Session, cs_batch, tag_batch, comment_batch)

    logging.info(f"Finished processing {processed} changesets from main file.")


def main():
    parser = argparse.ArgumentParser(
        description="Populate the database from OSM .osm.bz files."
    )
    parser.add_argument(
        "changeset_file", help="Path to the main .osm.bz changeset file"
    )
    parser.add_argument(
        "db_url", help="SQLAlchemy database URL (e.g. postgresql://user:pass@host/db)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE, help="Batch size for bulk inserts"
    )
    parser.add_argument(
        "--no-truncate",
        action="store_false",
        dest="truncate",
        help="Do not truncate the tables before loading",
    )
    parser.add_argument(
        "--from_date",
        type=valid_yyyymmdd,
        default=None,
        help="Date to start import from (YYYYMMDD)",
    )
    parser.add_argument(
        "--to_date",
        type=valid_yyyymmdd,
        default=None,
        help="Date to stop import at (YYYYMMDD)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    # Configure the engine with a connection pool.
    engine = create_engine(
        args.db_url,
        poolclass=QueuePool,
        pool_size=POOL_SIZE,
        max_overflow=20,
        pool_timeout=30,
        pool_pre_ping=True,
    )

    if args.truncate:
        # Check if tables exist before truncating
        with engine.connect() as conn:
            tables_exist = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'changesets'
                )
            """)).scalar()
            
            if tables_exist:
                logging.warning("Truncating existing tables")
                truncate_tables()
            else:
                logging.warning("Tables do not exist - creating them")
                create_tables()

    from_date = (
        datetime.strptime(args.from_date, "%Y%m%d").date() if args.from_date else None
    )
    to_date = datetime.strptime(args.to_date, "%Y%m%d").date() if args.to_date else None

    Session = sessionmaker(bind=engine)

    logging.info(
        f"Going to process {args.changeset_file} from {from_date} to {to_date}"
    )

    process_changeset_file(
        args.changeset_file,
        Session,
        from_date=from_date,
        to_date=to_date,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    # Skip table creation since they should already exist
    main()
