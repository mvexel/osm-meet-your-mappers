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
            # Start with the most recent possible sequence and work backwards
            current = StateFile(9_999_999)  # Arbitrary high number
            step = 10_000  # Start with a large step
            
            while step > 0:
                logger.debug(f"Checking sequence {current.sequence}")
                if current.fetch():
                    logger.info(f"Found current sequence: {current.sequence} with timestamp {current.timestamp}")
                    return Path(sequence=current.sequence)
                
                current = StateFile(current.sequence - step)
                
                if current.sequence < 2_007_990:  # This is when state files started
                    logger.warning("Reached earliest available state file (2007990), stopping search")
                    return None
                
                if step > 1:
                    step = step // 2  # Reduce step size for finer search
                    
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
