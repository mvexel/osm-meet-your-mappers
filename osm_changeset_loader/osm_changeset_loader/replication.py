"""OSM replication API client."""

from typing import Optional, List, Dict
import logging
import gzip
import requests
from xml.etree.ElementTree import fromstring
from dataclasses import dataclass
from datetime import datetime

from .model import Changeset
from .path import Path
from .config import Config
from .state import StateFile, find_sequence_for_timestamp

logger = logging.getLogger(__name__)


@dataclass
class ReplicationClient:
    config: Config

    def get_remote_state(self) -> Optional[Dict[str, any]]:
        """Get replication state from the OSM API
        by querying state.yaml"""
        try:
            state_url = f"{Config.REPLICATION_URL}/state.yaml"
            response = requests.get(state_url)
            response.raise_for_status()

            lines = response.text.strip().split("\n")[1:]
            last_run = datetime.fromisoformat(lines[0].split(": ")[1])
            sequence = int(lines[1].split(": ")[1])
            return {"last_run": last_run, "sequence": sequence}

        except requests.RequestException as e:
            logging.error(f"Error processing state.yaml: {e}")
            return None

    def backfill_changesets(self):
        """Backfill changesets by working backwards from the latest sequence."""
        state = self.get_remote_state()
        if not state:
            logger.error("Failed to fetch remote state.")
            return

        current_sequence = state["sequence"]

        while current_sequence >= 0:
            path = Path(sequence=current_sequence)
            changesets = self.get_changesets(path)

            if not changesets:
                logger.info(f"No changesets found for sequence {current_sequence}.")
                current_sequence -= 1
                continue

            for changeset in changesets:
                if self.changeset_exists(changeset.id):
                    logger.info(f"Changeset {changeset.id} already exists. Stopping backfill.")
                    return

                self.insert_changeset(changeset)

            logger.info(f"Processed sequence {current_sequence}.")
            current_sequence -= 1

    def changeset_exists(self, changeset_id: int) -> bool:
        """Check if a changeset already exists in the database."""
        # Implement database query to check for existing changeset
        pass

    def insert_changeset(self, changeset: Changeset):
        """Insert a new changeset into the database."""
        # Implement database insertion logic
        pass
        """Get changeset objects from replication path."""
        url = path.to_url()
        try:
            response = requests.get(url)
            response.raise_for_status()
            tree = fromstring(gzip.decompress(response.content))

            changesets = [
                Changeset.from_xml(elem)
                for elem in tree.findall("changeset")
                if self._is_valid_changeset(elem)
            ]

            logging.info(f"Downloaded {len(changesets)} changesets from {url}.")
            return changesets
        except requests.RequestException as e:
            logging.error(f"Error fetching changesets from {url}: {e}")
            return None

    def _is_valid_changeset(self, elem) -> bool:
        """Check if changeset is valid according to our criteria."""
        if elem.attrib.get("open") != "false":
            return False

        try:
            min_lat = float(elem.attrib.get("min_lat", 0))
            min_lon = float(elem.attrib.get("min_lon", 0))
            max_lat = float(elem.attrib.get("max_lat", 0))
            max_lon = float(elem.attrib.get("max_lon", 0))

            return (
                min_lat >= self.config.BBOX[1]
                and min_lon >= self.config.BBOX[0]
                and max_lat <= self.config.BBOX[3]
                and max_lon <= self.config.BBOX[2]
            )
        except (ValueError, TypeError):
            return False
