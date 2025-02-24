#!/usr/bin/env python3
import bz2
import io
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, List, Tuple

import psutil
from dotenv import load_dotenv
from lxml import etree
from psycopg2.extras import execute_values
from shapely import Point, box

from osm_meet_your_mappers.db import get_db_connection

load_dotenv()


class ConfigurationError(Exception):
    """Raised when there's an error in configuration."""

    pass


def get_env_config() -> Dict:
    """Get configuration from environment variables with defaults."""
    try:
        config = {
            "num_workers": int(os.getenv("LOADER_NUM_WORKERS", "4")),
            "queue_size": int(os.getenv("LOADER_QUEUE_SIZE", "1000")),
            "batch_size": int(os.getenv("LOADER_BATCH_SIZE", "50000")),
            "retention_period": os.getenv("RETENTION_PERIOD", "365 days"),
            "log_level": os.getenv("LOADER_LOGLEVEL", "INFO").upper(),
            "changeset_file": os.getenv("LOADER_CHANGESET_FILE"),
            "buffer_size": int(os.getenv("LOADER_BUFFER_SIZE", "262144")),  # 256KB
        }
        try:
            config["retention_days"] = int(config["retention_period"].split()[0])
        except (IndexError, ValueError):
            raise ConfigurationError("OSM_RETENTION_PERIOD must be in format 'X days'")

        return config
    except ValueError as e:
        raise ConfigurationError(f"Configuration error: {str(e)}")


def validate_config(config: Dict) -> None:
    """Validate configuration values."""
    if not config["changeset_file"]:
        raise ConfigurationError("OSM_CHANGESET_FILE environment variable not set")

    if not os.path.exists(config["changeset_file"]):
        raise ConfigurationError(
            f"Changeset file not found: {config['changeset_file']}"
        )

    if config["num_workers"] < 1:
        raise ConfigurationError("OSM_NUM_WORKERS must be at least 1")

    if config["queue_size"] < 1:
        raise ConfigurationError("OSM_QUEUE_SIZE must be at least 1")

    if config["batch_size"] < 1:
        raise ConfigurationError("OSM_BATCH_SIZE must be at least 1")


def log_memory_usage():
    process = psutil.Process()
    memory_info = process.memory_info()
    logging.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")


@lru_cache(maxsize=128)
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


def should_process_changeset(elem: etree._Element, cutoff_date: datetime) -> bool:
    """Quick check if changeset should be processed based on closed_at date."""
    closed_at_str = elem.attrib.get("closed_at")
    if not closed_at_str:
        return False

    try:
        closed_at = parse_datetime(closed_at_str)
        if closed_at is None:
            return False

        return closed_at >= cutoff_date
    except Exception as e:
        logging.debug(f"Error processing date {closed_at_str}: {e}")
        return False


def create_geometry(min_lon, min_lat, max_lon, max_lat):
    if abs(min_lon - max_lon) < 1e-7 and abs(min_lat - max_lat) < 1e-7:
        return f"POINT({min_lon} {min_lat})"
    return f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"


def parse_changeset(elem: etree._Element) -> Tuple[Dict, List, List]:
    """Parse a changeset element into database-ready dictionaries."""
    cs_id = int(elem.attrib.get("id", "0"))
    if cs_id <= 0:
        return None, [], []

    min_lon = float(elem.attrib.get("min_lon", 0))
    min_lat = float(elem.attrib.get("min_lat", 0))
    max_lon = float(elem.attrib.get("max_lon", 0))
    max_lat = float(elem.attrib.get("max_lat", 0))
    geometry = (
        box(min_lon, min_lat, max_lon, max_lat)
        if min_lon != min_lat and max_lon != max_lat
        else Point(min_lon, min_lat)
    )

    cs = {
        "id": cs_id,
        "username": elem.attrib.get("user"),
        "uid": int(elem.attrib.get("uid", 0)),
        "created_at": parse_datetime(elem.attrib.get("created_at")),
        "closed_at": parse_datetime(elem.attrib.get("closed_at")),
        "open": elem.attrib.get("open", "").lower() == "true",
        "num_changes": int(elem.attrib.get("num_changes", 0)),
        "comments_count": int(elem.attrib.get("comments_count", 0)),
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
        "bbox": f"SRID=4326;{geometry.wkt}",
    }

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


def process_batch(conn, batch_data):
    """Process a batch of changesets and write to database."""
    cs_batch, tag_batch, comment_batch = [], [], []

    logging.debug(f"Starting to process batch of {len(batch_data)} items")

    for cs, tags, comments in batch_data:
        cs_batch.append(cs)
        tag_batch.extend(tags)
        comment_batch.extend(comments)

    try:
        logging.debug(
            f"Attempting to insert batch: {len(cs_batch)} changesets, "
            f"{len(tag_batch)} tags, {len(comment_batch)} comments"
        )
        insert_batch(conn, cs_batch, tag_batch, comment_batch)
        logging.debug(f"Successfully inserted batch of {len(cs_batch)} changesets")
    except Exception as ex:
        logging.error(f"Error inserting batch: {ex}", exc_info=True)
        raise


def insert_batch(conn, cs_batch, tag_batch, comment_batch):
    try:
        with conn.cursor() as cur:
            if cs_batch:
                logging.debug(f"Inserting {len(cs_batch)} changesets")
                columns = (
                    "id",
                    "username",
                    "uid",
                    "created_at",
                    "closed_at",
                    "open",
                    "num_changes",
                    "comments_count",
                    "min_lat",
                    "min_lon",
                    "max_lat",
                    "max_lon",
                    "bbox",
                )
                execute_values(
                    cur,
                    f"INSERT INTO changesets ({','.join(columns)}) VALUES %s",
                    [tuple(cs[col] for col in columns) for cs in cs_batch],
                )

            if tag_batch:
                logging.debug(f"Inserting {len(tag_batch)} tags")
                columns = ("changeset_id", "k", "v")
                execute_values(
                    cur,
                    f"INSERT INTO changeset_tags ({','.join(columns)}) VALUES %s",
                    [tuple(tag[col] for col in columns) for tag in tag_batch],
                )

            if comment_batch:
                logging.debug(f"Inserting {len(comment_batch)} comments")
                columns = ("changeset_id", "uid", "username", "date", "text")
                execute_values(
                    cur,
                    f"INSERT INTO changeset_comments ({','.join(columns)}) VALUES %s",
                    [
                        tuple(comment[col] for col in columns)
                        for comment in comment_batch
                    ],
                )

            conn.commit()
            logging.debug("Successfully committed batch to database")
    except Exception as ex:
        conn.rollback()
        logging.error("Error during batch insert: %s", ex, exc_info=True)
        raise


def producer(
    filename: str, work_queue: queue.Queue, cutoff_date: datetime, config: Dict
):
    """Producer function with configuration."""
    batch = []
    processed = 0
    skipped = 0
    last_log_time = time.time()
    log_interval = 10  # Log every 10 seconds
    queue_high_water_mark = config["queue_size"] * 0.8  # 80% of max queue size

    try:
        logging.info("Starting to read bzip2 file...")
        with bz2.open(filename, "rb") as raw_f, io.BufferedReader(
            raw_f, buffer_size=config["buffer_size"]
        ) as f:
            logging.info("Successfully opened bzip2 file, creating buffered reader...")
            logging.info("Starting XML parsing...")

            context = etree.iterparse(f, events=("start", "end"), tag="changeset")
            total_elements = 0

            for event, elem in context:
                current_time = time.time()

                if event == "end":
                    total_elements += 1

                    # Add backpressure when queue is getting full
                    while work_queue.qsize() >= queue_high_water_mark:
                        logging.debug("Queue nearly full, sleeping...")
                        time.sleep(1)

                    if current_time - last_log_time >= log_interval:
                        logging.info(
                            f"Progress: processed={processed}, skipped={skipped}, "
                            f"total_seen={total_elements}, queue_size={work_queue.qsize()}"
                        )
                        log_memory_usage()
                        last_log_time = current_time

                    try:
                        if should_process_changeset(elem, cutoff_date):
                            parsed = parse_changeset(elem)
                            if parsed[0]:
                                batch.append(parsed)
                                processed += 1

                                if len(batch) >= config["batch_size"]:
                                    logging.debug(
                                        f"Queueing batch of {len(batch)} items..."
                                    )
                                    # Add timeout to queue.put()
                                    try:
                                        work_queue.put(
                                            batch, timeout=300
                                        )  # 5 minute timeout
                                        batch = []
                                        logging.debug(
                                            f"Batch queued. Total processed: {processed}, "
                                            f"skipped: {skipped}, queue size: {work_queue.qsize()}"
                                        )
                                    except queue.Full:
                                        logging.error(
                                            "Queue full after timeout, exiting"
                                        )
                                        raise
                        else:
                            skipped += 1

                    except Exception as e:
                        logging.error(f"Error processing changeset: {e}")
                    finally:
                        elem.clear()
                        while elem.getprevious() is not None:
                            del elem.getparent()[0]

        if batch:
            logging.info(f"Queueing final batch of {len(batch)} items...")
            work_queue.put(batch, timeout=300)

        logging.info("Producer finished, sending termination signals...")
        for _ in range(config["num_workers"]):
            work_queue.put(None, timeout=300)

    except Exception as e:
        logging.error(
            f"Fatal error in producer: {e}. Are you sure the file exists on the host file system?",
            exc_info=True,
        )
        # Make sure to send termination signals even on error
        for _ in range(config["num_workers"]):
            try:
                work_queue.put(None, timeout=10)
            except queue.Full:
                pass
        raise

    logging.info(
        f"Producer complete. Total elements seen: {total_elements}, "
        f"processed: {processed}, skipped: {skipped}"
    )


def consumer(work_queue: queue.Queue, conn, config: Dict):
    """Process batches from the work queue with longer timeout."""
    processed_batches = 0
    processed_items = 0
    thread_name = threading.current_thread().name
    TIMEOUT = 3600  # 1 hour timeout

    logging.info(f"Consumer {thread_name} starting...")

    while True:
        try:
            batch = work_queue.get(timeout=TIMEOUT)  # 1 hour timeout

            if batch is None:  # poison pill
                logging.info(f"Consumer {thread_name} received termination signal")
                work_queue.task_done()
                break

            batch_size = len(batch)
            try:
                process_batch(conn, batch)
                processed_batches += 1
                processed_items += batch_size
                logging.info(
                    f"Consumer {thread_name}: processed batch {processed_batches} "
                    f"({batch_size} items, total {processed_items})"
                )
            except Exception as e:
                logging.error(f"Error processing batch in {thread_name}: {e}")
            finally:
                work_queue.task_done()

        except queue.Empty:
            logging.warning(
                f"Consumer {thread_name}: No data received for {TIMEOUT} seconds, timing out"
            )
            break

    logging.info(
        f"Consumer {thread_name} finished. Processed {processed_batches} batches, "
        f"{processed_items} items"
    )


def process_changeset_file(config: Dict):
    """Main processing function with delayed consumer start."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=config["retention_days"])

    logging.info(f"Starting processing of {config['changeset_file']}")
    logging.info(
        f"Processing changesets since {cutoff_date.isoformat()} "
        f"({config['retention_days']} days retention)"
    )

    file_size_mb = os.path.getsize(config["changeset_file"]) / (1024 * 1024)
    logging.info(f"File size: {file_size_mb:.2f} MB")

    # Create work queue
    work_queue = queue.Queue(maxsize=config["queue_size"])

    # Start producer thread
    producer_thread = threading.Thread(
        target=producer,
        args=(config["changeset_file"], work_queue, cutoff_date, config),
    )
    producer_thread.start()

    # Wait for the first batch to be available before starting consumers
    logging.info("Waiting for initial data from producer...")
    while producer_thread.is_alive():
        if not work_queue.empty():
            break
        time.sleep(10)  # Check every 10 seconds
        logging.info("Still waiting for initial data...")

    if not producer_thread.is_alive() and work_queue.empty():
        logging.error("Producer terminated without producing any data")
        return

    logging.info("Initial data available, starting consumers...")

    # Start consumer threads
    consumers = []
    for i in range(config["num_workers"]):
        conn = get_db_connection()
        consumer_thread = threading.Thread(
            target=consumer, args=(work_queue, conn, config), name=f"Consumer-{i}"
        )
        consumer_thread.start()
        consumers.append((consumer_thread, conn))

    # Wait for all work to complete
    producer_thread.join()
    work_queue.join()

    # Clean up connections
    for thread, conn in consumers:
        thread.join()
        conn.close()

    logging.info("Processing complete")


def main():
    try:
        # Load and validate configuration
        config = get_env_config()
        validate_config(config)

        # Setup logging
        logging.basicConfig(
            level=config["log_level"], format="%(asctime)s %(levelname)s: %(message)s"
        )

        # Log configuration
        logging.info("Starting with configuration:")
        for key, value in config.items():
            logging.info(f"- {key}: {value}")

        # Initialize database
        conn = get_db_connection()

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

        # Process changesets
        try:
            process_changeset_file(config)
        finally:
            conn.close()

    except ConfigurationError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
