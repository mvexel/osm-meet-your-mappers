import json
import logging
import threading
from datetime import datetime
from textwrap import dedent
from typing import List, Optional, Tuple

from psycopg2.extras import execute_values


def get_duplicate_ids(conn, cs_batch):
    """Return a set of changeset IDs that already exist in the database."""
    cs_ids = [cs["id"] for cs in cs_batch]
    if not cs_ids:
        return set()

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM changesets WHERE id = ANY(%s)", (cs_ids,))
        return {row[0] for row in cur.fetchall()}


def upsert_changesets(conn, cs_batch):
    if not cs_batch:
        return

    # First, get existing changeset data to make smart update decisions
    cs_ids = [cs["id"] for cs in cs_batch]
    existing_data = {}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, closed_at, open, comments_count FROM changesets WHERE id = ANY(%s)",
            (cs_ids,),
        )
        existing_data = {
            row[0]: {"closed_at": row[1], "open": row[2], "comments_count": row[3]}
            for row in cur.fetchall()
        }

    # Filter out changesets that would overwrite closed with open
    filtered_batch = []
    for cs in cs_batch:
        cs_id = cs["id"]

        # If this changeset exists in our database
        if cs_id in existing_data:
            existing = existing_data[cs_id]

            # If existing is closed but new one is open, skip it
            if existing["closed_at"] and not cs.get("closed_at"):
                logging.debug(
                    f"Skipping changeset {cs_id}: would overwrite closed with open"
                )
                continue

            # If existing has more comments than new one, skip it
            if existing["comments_count"] > cs.get("comments_count", 0):
                logging.debug(f"Skipping changeset {cs_id}: existing has more comments")
                continue

        filtered_batch.append(cs)

    if not filtered_batch:
        logging.debug("No changesets to update after filtering")
        return

    columns = (
        "id",
        "username",
        "uid",
        "created_at",
        "closed_at",
        "open",
        "num_changes",
        "comments_count",
        "tags",
        "comments",
        "bbox",
    )

    data = [
        (
            cs["id"],
            cs["username"],
            cs["uid"],
            cs["created_at"],
            cs["closed_at"],
            cs["open"],
            cs["num_changes"],
            cs["comments_count"],
            json.dumps(cs["tags"] or {}),
            json.dumps(cs["comments"] or []),
            cs["bbox"] or "POINT EMPTY",
        )
        for cs in filtered_batch
    ]

    query = dedent(
        f"""
        INSERT INTO changesets ({','.join(columns)})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            username = EXCLUDED.username,
            uid = EXCLUDED.uid,
            created_at = EXCLUDED.created_at,
            -- Only update closed_at if it's NULL in the database or the new one is not NULL
            closed_at = CASE 
                WHEN changesets.closed_at IS NULL THEN EXCLUDED.closed_at
                WHEN EXCLUDED.closed_at IS NULL THEN changesets.closed_at
                ELSE EXCLUDED.closed_at
            END,
            -- Only update open status if we're closing a changeset
            open = CASE
                WHEN EXCLUDED.open = false THEN false
                ELSE changesets.open
            END,
            num_changes = EXCLUDED.num_changes,
            comments_count = EXCLUDED.comments_count,
            tags = EXCLUDED.tags,
            comments = changesets.comments || EXCLUDED.comments,
            bbox = EXCLUDED.bbox
    """
    )

    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                query,
                data,
                template="""
                (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                ST_GeomFromText(%s, 4326))
                """,
            )
            conn.commit()
            logging.debug(f"Inserted/Updated {len(filtered_batch)} changesets.")

    except Exception as ex:
        logging.error("Batch insert failed: %s", ex, exc_info=True)
        conn.rollback()
    finally:
        if conn.closed:
            logging.warning("Connection was closed unexpectedly.")


def filter_new_changesets(conn, cs_batch: List[dict]) -> List[dict]:
    """Remove changesets that already exist in the database."""
    dup_ids = get_duplicate_ids(conn, cs_batch)
    new_cs_batch = [cs for cs in cs_batch if cs["id"] not in dup_ids]
    return new_cs_batch


def upsert_changeset_batch(conn, cs_batch: List[dict]) -> Tuple[int, datetime]:
    """Upsert changesets and return count + earliest created_at timestamp."""
    upsert_changesets(conn, cs_batch)
    inserted_count = len(cs_batch)
    batch_min_ts = min(cs["created_at"] for cs in cs_batch)
    most_recent_closed_at = max(cs["closed_at"] for cs in cs_batch)

    logging.info(
        f"[{threading.current_thread().name}] Inserted {inserted_count} changesets, "
        f"newest closed_at: {most_recent_closed_at}"
    )
    return inserted_count, batch_min_ts


def update_min_timestamp(current_min: Optional[datetime], new_ts: datetime) -> datetime:
    """Return the earlier of two timestamps."""
    return min(current_min, new_ts) if current_min else new_ts
