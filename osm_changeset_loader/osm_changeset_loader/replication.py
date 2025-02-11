"""OSM replication API client."""

from typing import Optional, List
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

    def get_remote_state(self) -> Optional[Path]:
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

    def get_changesets(self, path: Path) -> Optional[List[Changeset]]:
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
