#!/usr/bin/env python3
import gzip
import io
import json
import logging
import os
import xml.etree.ElementTree as ET

import requests
import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def update_last_sequence(conn, seq):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO replication_state (id, last_seq)
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE SET last_seq = EXCLUDED.last_seq
        """,
            (seq,),
        )
    conn.commit()


def get_last_sequence(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT last_seq FROM replication_state WHERE id = 1")
        row = cur.fetchone()
        return row[0] if row else None


def fetch_current_state():
    state_url = os.environ.get("REPLICATION_BASE_URL") + "/state.yaml"
    resp = requests.get(state_url)
    resp.raise_for_status()
    state = yaml.safe_load(resp.text)
    return int(state["sequence"])


def get_changeset_url(seq):
    """
    Format a replication file URL from the sequence number.
    Example: sequence 6382422 -> "https://planet.openstreetmap.org/replication/changesets/006/410/422.osm.gz"
    """
    seq_str = str(seq).zfill(9)
    return f"https://planet.openstreetmap.org/replication/changesets/{seq_str[:3]}/{seq_str[3:6]}/{seq_str[6:]}.osm.gz"


def parse_changeset_element(elem):
    """
    Parse a <changeset> XML element into a dictionary matching our DB schema.
    Builds a WKT bounding box from the envelope and converts tag and discussion
    elements into JSON strings.
    """
    cs = {}
    cs["id"] = int(elem.attrib["id"])
    cs["created_at"] = elem.attrib.get("created_at")
    cs["closed_at"] = elem.attrib.get("closed_at")
    cs["open"] = elem.attrib.get("open") == "true"
    cs["num_changes"] = int(elem.attrib.get("num_changes", "0"))
    cs["username"] = elem.attrib.get("user")
    cs["uid"] = int(elem.attrib.get("uid")) if elem.attrib.get("uid") else None
    cs["comments_count"] = int(elem.attrib.get("comments_count", "0"))

    # Create a bounding box polygon if coordinates are available.
    min_lat = elem.attrib.get("min_lat")
    max_lat = elem.attrib.get("max_lat")
    min_lon = elem.attrib.get("min_lon")
    max_lon = elem.attrib.get("max_lon")
    if min_lat and max_lat and min_lon and max_lon:
        cs["bbox"] = (
            f"POLYGON(({min_lon} {min_lat}, {min_lon} {max_lat}, {max_lon} {max_lat}, {max_lon} {min_lat}, {min_lon} {min_lat}))"
        )
    else:
        cs["bbox"] = None

    # Convert <tag> elements to JSON
    tags = {}
    for tag in elem.findall("tag"):
        tags[tag.attrib.get("k")] = tag.attrib.get("v")
    cs["tags"] = json.dumps(tags)

    # Process discussion comments if present.
    comments = []
    discussion = elem.find("discussion")
    if discussion is not None:
        for comment in discussion.findall("comment"):
            comment_obj = {
                "id": comment.attrib.get("id"),
                "uid": comment.attrib.get("uid"),
                "user": comment.attrib.get("user"),
                "date": comment.attrib.get("date"),
                "text": comment.findtext("text"),
            }
            comments.append(comment_obj)
    cs["comments"] = json.dumps(comments)

    return cs


def changeset_exists_and_equal(conn, cs):
    """
    Checks if a changeset already exists in the DB with identical content.
    Compares fields including timestamps, JSON fields (as text) and the WKT bbox.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT created_at, closed_at, open, num_changes, username, uid, comments_count, tags::text, comments::text, ST_AsText(bbox)
            FROM changesets WHERE id = %s
        """,
            (cs["id"],),
        )
        row = cur.fetchone()
        if not row:
            return False
        # Normalize the DB record for comparison.
        db_record = {
            "created_at": row[0].isoformat() if row[0] else None,
            "closed_at": row[1].isoformat() if row[1] else None,
            "open": row[2],
            "num_changes": row[3],
            "username": row[4],
            "uid": row[5],
            "comments_count": row[6],
            "tags": row[7],
            "comments": row[8],
            "bbox": row[9],
        }
        cs_compare = {
            "created_at": cs["created_at"],
            "closed_at": cs["closed_at"],
            "open": cs["open"],
            "num_changes": cs["num_changes"],
            "username": cs["username"],
            "uid": cs["uid"],
            "comments_count": cs["comments_count"],
            "tags": cs["tags"],
            "comments": cs["comments"],
            "bbox": cs["bbox"],
        }
        return db_record == cs_compare


def upsert_changeset(conn, cs):
    """
    Inserts a changeset into the DB or updates it if it already exists,
    using PostgreSQL's UPSERT via ON CONFLICT.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO changesets (id, created_at, closed_at, open, num_changes, username, uid, comments_count, tags, comments, bbox)
            VALUES (
                %(id)s,
                %(created_at)s,
                %(closed_at)s,
                %(open)s,
                %(num_changes)s,
                %(username)s,
                %(uid)s,
                %(comments_count)s,
                %(tags)s,
                %(comments)s,
                ST_GeomFromText(%(bbox)s, 4326)
            )
            ON CONFLICT (id) DO UPDATE SET
                created_at = EXCLUDED.created_at,
                closed_at = EXCLUDED.closed_at,
                open = EXCLUDED.open,
                num_changes = EXCLUDED.num_changes,
                username = EXCLUDED.username,
                uid = EXCLUDED.uid,
                comments_count = EXCLUDED.comments_count,
                tags = EXCLUDED.tags,
                comments = EXCLUDED.comments,
                bbox = EXCLUDED.bbox
        """,
            cs,
        )
    conn.commit()


def process_replication_file(conn, seq):
    """
    Downloads, decompresses, and processes a replication XML file identified by its sequence number.
    Returns True if at least one changeset was inserted/updated; False if all changesets were already present.
    """
    url = get_changeset_url(seq)
    logging.info(f"Processing sequence {seq}: {url}")
    try:
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            logging.error(f"Failed to fetch {url}: HTTP {response.status_code}")
            return None
        # Decompress gzipped content.
        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
            xml_data = f.read()
        root = ET.fromstring(xml_data)
    except Exception as e:
        logging.exception(f"Error processing file {url}: {e}")
        return None

    changesets = root.findall("changeset")
    file_has_changes = False
    for cs_elem in changesets:
        cs = parse_changeset_element(cs_elem)
        if changeset_exists_and_equal(conn, cs):
            logging.debug(f"Changeset {cs['id']} exists and is identical. Skipping.")
            continue
        else:
            logging.info(f"Inserting/updating changeset {cs['id']}")
            upsert_changeset(conn, cs)
            file_has_changes = True
    return file_has_changes


def main():
    import logging
    import sys
    import time

    import psycopg2

    # Build the DB connection string from environment variables.
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    dbname = os.environ.get("POSTGRES_DB")
    host = os.environ.get("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db_conn_str = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    # Get the starting sequence from environment variables.
    start_seq_str = os.environ.get("START_SEQ")
    if not start_seq_str:
        logging.error("START_SEQ environment variable not set.")
        sys.exit(1)
    try:
        start_seq = int(start_seq_str)
    except ValueError:
        logging.error("Invalid START_SEQ value: must be an integer")
        sys.exit(1)

    # Connect to the database.
    try:
        conn = psycopg2.connect(db_conn_str)
    except Exception as e:
        logging.error(f"Unable to connect to database: {e}")
        sys.exit(1)

    # Retrieve the last saved sequence number, or use start_seq if none exists.
    last_seq = get_last_sequence(conn)
    current_seq = last_seq if last_seq is not None else start_seq
    logging.info(f"Resuming from sequence {current_seq}")
    update_last_sequence(conn, current_seq)

    try:
        while True:
            # Fetch the latest live sequence from the state file.
            try:
                latest_seq = fetch_current_state()
            except Exception as e:
                logging.error(f"Failed to fetch state.yaml: {e}")
                time.sleep(60)
                continue

            if current_seq <= latest_seq:
                result = process_replication_file(conn, current_seq)
                if result is None:
                    logging.info(
                        f"Replication file for sequence {current_seq} not available yet. Waiting..."
                    )
                    time.sleep(60)
                else:
                    logging.info(f"Processed sequence {current_seq}")
                    current_seq += 1
                    update_last_sequence(conn, current_seq)
            else:
                logging.info(
                    "Caught up with the live state. Waiting for new replication files..."
                )
                time.sleep(60)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
