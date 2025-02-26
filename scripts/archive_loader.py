#!/usr/bin/env python3
import bz2
import io
import logging
import queue
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from dotenv import load_dotenv
from lxml import etree

from osm_meet_your_mappers.config import (
    ConfigurationError,
    get_env_config,
    validate_config,
)
from osm_meet_your_mappers.db import get_db_connection
from osm_meet_your_mappers.db_utils import get_duplicate_ids, upsert_changesets
from osm_meet_your_mappers.parsers import parse_changeset, parse_datetime

load_dotenv()

# Thread safety lock
insert_lock = threading.Lock()


def insert_changeset_batch(conn, cs_batch: List[dict]) -> None:
    """Insert or update changesets into the database."""
    if not cs_batch:
        return

    with insert_lock:
        # Validate batch structure
        valid_batch = []
        for cs in cs_batch:
            if not isinstance(cs, dict):
                logging.warning(f"Skipping invalid changeset (not a dict): {cs}")
                continue
            if "id" not in cs:
                logging.warning(f"Skipping changeset missing 'id': {cs}")
                continue
            valid_batch.append(cs)

        if not valid_batch:
            logging.warning("No valid changesets in batch")
            return

        dup_ids = get_duplicate_ids(conn, valid_batch)
        new_cs_batch = [cs for cs in valid_batch if cs["id"] not in dup_ids]

        if new_cs_batch:
            try:
                logging.debug(f"Inserting batch with first changeset: {new_cs_batch[0]}")
                upsert_changesets(conn, new_cs_batch)
                logging.info(f"Inserted/updated {len(new_cs_batch)} changesets.")
            except Exception as e:
                logging.error(f"Batch insert failed: {e}")
                logging.debug(f"Problematic batch: {new_cs_batch}")
                raise


def producer(
    filename: str, work_queue: queue.Queue, cutoff_date: datetime, config: Dict
):
    """Read changesets from file and queue them for processing."""
    batch = []
    processed, skipped = 0, 0

    logging.info(f"Producer started. Cutoff date: {cutoff_date.isoformat()}")
    logging.info(f"Reading from file: {filename}")

    with bz2.open(filename, "rb") as raw_file, io.BufferedReader(
        raw_file, buffer_size=config["buffer_size"]
    ) as file:
        context = etree.iterparse(file, events=("end",), tag="changeset")

        for i, (_, elem) in enumerate(context, start=1):
            closed_at = elem.attrib.get("closed_at")
            if closed_at and parse_datetime(closed_at) >= cutoff_date:
                cs = parse_changeset(elem)
                if cs:
                    batch.append(cs)
                    processed += 1

                    if len(batch) >= config["batch_size"]:
                        work_queue.put(batch)
                        batch = []
            else:
                skipped += 1

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            if i % 10000 == 0:
                logging.info(
                    f"Processed {i} changesets... (Queued: {processed}, Skipped: {skipped})"
                )

    if batch:
        work_queue.put(batch)

    logging.info(
        f"Producer finished: {processed} queued for processing, {skipped} skipped."
    )
    for _ in range(config["num_workers"]):
        work_queue.put(None)  # Poison pills for consumers


def consumer(work_queue: queue.Queue, conn, config: Dict):
    """Consume batches from the queue and insert them into the database."""
    logging.info("Consumer started.")
    while True:
        batch = work_queue.get()
        if batch is None:
            logging.info("Consumer received shutdown signal.")
            break

        try:
            insert_changeset_batch(conn, batch)
        except Exception as ex:
            logging.error(f"Error inserting batch: {ex}", exc_info=True)

        work_queue.task_done()
    logging.info("Consumer exiting.")


def process_changeset_file(config: Dict):
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=config["retention_days"])
    work_queue = queue.Queue(maxsize=config["queue_size"])

    producer_thread = threading.Thread(
        target=producer,
        args=(config["changeset_file"], work_queue, cutoff_date, config),
        name="Producer",
    )
    producer_thread.start()

    consumers = []
    for i in range(config["num_workers"]):
        conn = get_db_connection()
        consumer_thread = threading.Thread(
            target=consumer,
            args=(work_queue, conn, config),
            name=f"Consumer-{i+1}",
        )
        consumer_thread.start()
        consumers.append((consumer_thread, conn))

    producer_thread.join()
    work_queue.join()

    for thread, conn in consumers:
        thread.join()
        conn.close()

    logging.info("All processing complete.")


def main():
    try:
        config = get_env_config()
        validate_config(config)

        logging.basicConfig(
            level=config["log_level"],
            format="%(asctime)s %(levelname)s [%(threadName)s]: %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('archive_loader.log')
            ]
        )

        logging.info("Starting archive loader with configuration:")
        for key, value in config.items():
            logging.info(f"  {key}: {value}")

        process_changeset_file(config)

    except ConfigurationError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
