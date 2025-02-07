import requests
import logging
import time
from model import Changeset, Metadata
from db import create_tables, get_db_session
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime
import gzip
from xml.etree.ElementTree import fromstring
import os
import signal
from path import Path

# Global bounding box
BBOX = [-180, -90, 180, 90]

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def init_db():
    """
    Initialize the database.
    """
    create_tables()


def get_local_state():
    """
    Get the local state from the database.
    """
    session = get_db_session()
    state = session.query(Metadata).order_by(Metadata.timestamp).first()
    if state:
        return Path(sequence=int(state.state))
    else:
        return Path(sequence=0)


def set_local_state(state):
    """
    Set the local state in the database.
    """
    session = get_db_session()
    metadata = Metadata(state=str(state.sequence), timestamp=datetime.now())
    session.add(metadata)
    session.commit()


def get_changesets_from_repl(path):
    """
    Get changeset objects from replication path.
    """
    url = path.to_url()
    try:
        response = requests.get(url)
        response.raise_for_status()
        tree = fromstring(gzip.decompress(response.content))
        changesets = [
            Changeset.from_xml(elem)
            for elem in tree.findall("changeset")
            if elem.attrib.get("open", None) == "false"
            and float(elem.attrib.get("min_lat", 0)) >= BBOX[1]
            and float(elem.attrib.get("min_lon", 0)) >= BBOX[0]
            and float(elem.attrib.get("max_lat", 0)) <= BBOX[3]
            and float(elem.attrib.get("max_lon", 0)) <= BBOX[2]
        ]
        logging.info(f"Downloaded {len(changesets)} changesets from {url}.")
        return changesets
    except requests.RequestException as e:
        logging.error(f"Error fetching changesets from {url}: {e}")
        return None


def insert_changesets(changesets):
    """
    Insert changesets into database.
    """
    session = get_db_session()

    values = [
        {
            "id": cs.id,
            "user": cs.user,
            "uid": cs.uid,
            "created_at": cs.created_at,
            "closed_at": cs.closed_at,
            "open": cs.open,
            "min_lat": cs.min_lat,
            "min_lon": cs.min_lon,
            "max_lat": cs.max_lat,
            "max_lon": cs.max_lon,
            "bbox_area_km2": cs.bbox_area_km2,
            "centroid_lon": cs.centroid_lon,
            "centroid_lat": cs.centroid_lat,
        }
        for cs in changesets
    ]
    if len(values) == 0:
        logging.info("No changesets to insert.")
        return False

    statement = insert(Changeset).values(values)
    do_update = statement.on_conflict_do_update(
        index_elements=[Changeset.id],
        set_={
            "user": statement.excluded.user,
            "uid": statement.excluded.uid,
            "created_at": statement.excluded.created_at,
            "closed_at": statement.excluded.closed_at,
            "open": statement.excluded.open,
            "min_lat": statement.excluded.min_lat,
            "min_lon": statement.excluded.min_lon,
            "max_lat": statement.excluded.max_lat,
            "max_lon": statement.excluded.max_lon,
            "bbox_area_km2": statement.excluded.bbox_area_km2,
            "centroid_lon": statement.excluded.centroid_lon,
            "centroid_lat": statement.excluded.centroid_lat,
        },
    )

    try:
        session.execute(do_update)
        session.commit()
        return True
    except Exception as e:
        logging.error(f"Error inserting changesets: {e}")
        session.rollback()
        return False


def catch_up():
    """
    Work backwards from current remote state, retrieving minutely files counting backwards and inserting them into the database.
    """
    latest_path = get_remote_state()
    local_state = get_local_state()

    while True:
        # Work backwards from current remote state to local state
        current_sequence = latest_path.sequence
        while current_sequence > local_state.sequence:
            current_path = Path(sequence=current_sequence)
            logging.info(f"Processing sequence {current_sequence}")

            changesets = get_changesets_from_repl(current_path)
            if changesets:
                if insert_changesets(changesets):
                    set_local_state(current_path)

            current_sequence -= 1

        # Check for new remote state
        latest_path = get_remote_state()
        if not latest_path:
            logging.error("Failed to get remote state, retrying in 60 seconds")
            time.sleep(60)
            continue

        time.sleep(60)  # Wait before next check


def get_remote_state():
    """
    Get the latest replication state from the OSM API.
    """
    try:
        response = requests.get(
            "https://planet.osm.org/replication/changesets/state.yaml"
        )
        response.raise_for_status()
        state = response.text.split("\n")[2]
        _, sequence = state.split(": ")
        sequence = sequence.strip()
        logging.debug(f"remote state is {sequence}")
        return Path(sequence=int(sequence))
    except requests.RequestException as e:
        logging.error(f"Error fetching remote state: {e}")
        return None


def handle_exit(signum, frame):
    logging.info("Exiting gracefully...")
    exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    init_db()
    catch_up()
