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


@dataclass
class ReplicationClient:
    config: Config

    def get_remote_state(self, for_timestamp: datetime = None) -> Optional[Path]:
        """Get replication state from the OSM API, optionally for a specific timestamp."""
        try:
            if for_timestamp:
                # Find the sequence number for this timestamp
                sequence = find_sequence_for_timestamp(for_timestamp)
                if sequence:
                    return Path(sequence=sequence)
                return None
                
            # Get current sequence by checking recent state files
            current = StateFile(6_000_000)  # Start with a reasonable current guess
            while True:
                if current.fetch():
                    return Path(sequence=current.sequence)
                current = StateFile(current.sequence - 100_000)
                if current.sequence < 1:
                    return None
                    
        except Exception as e:
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
