#!/usr/bin/env python3
import argparse
import bz2
import logging
import os
from datetime import datetime
from typing import Optional
from osm_meet_your_mappers.db import get_db_connection

import psycopg2
from dotenv import load_dotenv
from lxml import etree
from psycopg2.extras import execute_batch
from shapely.geometry import box

load_dotenv()

NUM_WORKERS = 4


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
    elem: etree._Element,
    from_date: Optional[datetime.date],
    to_date: Optional[datetime.date],
):
    try:
        cs_id = int(elem.attrib.get("id", "0"))
        if cs_id <= 0:
            return None
    except ValueError:
        return None

    created_at = parse_datetime(elem.attrib.get("created_at"))
    if created_at is None:
        return None

    if from_date and created_at.date() < from_date:
        return None
    if to_date and created_at.date() > to_date:
        return None

    cs = {
        "id": cs_id,
        "username": elem.attrib.get("user"),
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
    cs["bbox"] = (
        f"SRID=4326;{box(cs['min_lon'], cs['min_lat'], cs['max_lon'], cs['max_lat']).wkt}"
    )

    tags = [
        {"changeset_id": cs_id, "k": tag.attrib["k"], "v": tag.attrib.get("v")}
        for tag in elem.findall("tag")
    ]

    comments = []
    discussion = elem.find("discussion")
    if discussion is not None:
        for comment in discussion.findall("comment"):
            comments.append(
                {
                    "changeset_id": cs_id,
                    "uid": int(comment.attrib.get("uid", 0)),
                    "username": comment.attrib.get("username"),
                    "date": parse_datetime(comment.attrib.get("date")),
                    "text": comment.findtext("text"),
                }
            )

    return cs, tags, comments


def insert_batch(conn, cs_batch, tag_batch, comment_batch):
    try:
        with conn.cursor() as cur:
            if cs_batch:
                execute_batch(
                    cur,
                    """
                    INSERT INTO changesets (id, username, uid, created_at, closed_at, open, num_changes, comments_count, min_lat, min_lon, max_lat, max_lon, bbox)
                    VALUES (%(id)s, %(username)s, %(uid)s, %(created_at)s, %(closed_at)s, %(open)s, %(num_changes)s, %(comments_count)s, %(min_lat)s, %(min_lon)s, %(max_lat)s, %(max_lon)s, %(bbox)s)
                """,
                    cs_batch,
                )
            if tag_batch:
                execute_batch(
                    cur,
                    """
                    INSERT INTO changeset_tags (changeset_id, k, v)
                    VALUES (%(changeset_id)s, %(k)s, %(v)s)
                """,
                    tag_batch,
                )
            if comment_batch:
                execute_batch(
                    cur,
                    """
                    INSERT INTO changeset_comments (changeset_id, uid, username, date, text)
                    VALUES (%(changeset_id)s, %(uid)s, %(username)s, %(date)s, %(text)s)
                """,
                    comment_batch,
                )
            conn.commit()
    except Exception as ex:
        conn.rollback()
        logging.error("Error during batch insert: %s", ex)
        raise


def process_changeset_file(
    filename,
    Session,
    from_date,
    to_date,
    batch_size,
):
    with bz2.open(filename, "rb") as f:
        cs_batch, tag_batch, comment_batch = [], [], []
        processed = 0
        batch_counter = 0

        context = etree.iterparse(f, events=("end",), tag="changeset")
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
                    min_created_at = min(cs["created_at"] for cs in cs_batch)
                    logging.info(
                        f"Queueing batch #{batch_counter} with {len(cs_batch)} changesets, starting at {min_created_at}"
                    )
                    insert_batch(
                        Session, cs_batch.copy(), tag_batch.copy(), comment_batch.copy()
                    )
                    cs_batch.clear()
                    tag_batch.clear()
                    comment_batch.clear()

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        if cs_batch:
            logging.info("Inserting final batch")
            insert_batch(Session, cs_batch, tag_batch, comment_batch)

        logging.info(f"Finished processing {processed} changesets from chunk.")


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )

    changeset_file = os.getenv("CHANGESET_FILE")
    batch_size = int(os.getenv("BATCH_SIZE", 50000))
    truncate = os.getenv("TRUNCATE", "true").lower() == "true"
    from_date = os.getenv("FROM_DATE")
    to_date = os.getenv("TO_DATE")

    conn = get_db_connection()

    if truncate:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'changesets')"
            )
            tables_exist = cur.fetchone()[0]
            logging.info(f"Tables exist: {tables_exist}")
            if tables_exist:
                logging.warning("Truncating existing tables")
                cur.execute(
                    "TRUNCATE TABLE changesets, changeset_tags, changeset_comments CASCADE"
                )
                conn.commit()
            else:
                logging.warning("Tables do not exist – ensure migration has been run.")

    from_date = datetime.strptime(from_date, "%Y%m%d").date() if from_date else None
    to_date = datetime.strptime(to_date, "%Y%m%d").date() if to_date else None
    logging.info(f"Going to process {changeset_file} from {from_date} to {to_date}")

    process_changeset_file(changeset_file, conn, from_date, to_date, batch_size)
    conn.close()


if __name__ == "__main__":
    main()
