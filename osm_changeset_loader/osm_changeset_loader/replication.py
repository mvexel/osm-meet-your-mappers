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


@dataclass
class ReplicationClient:
    config: Config

    def get_remote_state(self) -> Optional[Path]:
        """Get the latest replication state from the OSM API."""
        try:
            response = requests.get(f"{self.config.REPLICATION_URL}/state.yaml")
            response.raise_for_status()
            state = response.text.split("\n")[2]
            _, sequence = state.split(": ")
            sequence = sequence.strip()
            logging.debug(f"remote state is {sequence}")
            return Path(sequence=int(sequence))
        except requests.RequestException as e:
            logging.error(f"Error fetching remote state: {e}")
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
