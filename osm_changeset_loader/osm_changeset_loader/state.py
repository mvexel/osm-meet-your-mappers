import logging
import re
import requests
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class StateFile:
    """Handles reading and parsing OSM replication state files"""

    def __init__(self, sequence: int):
        self.sequence = sequence
        self._timestamp: Optional[datetime] = None

    @property
    def path(self) -> str:
        """Convert sequence number to path format (e.g., 123456 -> 000/123/456)"""
        seq_str = f"{self.sequence:09d}"
        return f"{seq_str[0:3]}/{seq_str[3:6]}/{seq_str[6:9]}"

    @property
    def url(self) -> str:
        """Get the full URL to the state file"""
        return f"https://planet.osm.org/replication/changesets/{self.path}.state.txt"

    def fetch(self) -> Optional[datetime]:
        """Fetch and parse the state file, returns timestamp if successful"""
        try:
            logger.debug(f"Fetching state file from {self.url}")
            response = requests.get(self.url, timeout=30)
            response.raise_for_status()

            logger.debug(f"Got response: {response.text}")
            # Parse timestamp from state file
            # Example format: timestamp=2020-01-01T05:46:00Z
            match = re.search(
                r"timestamp=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", response.text
            )
            if match:
                self._timestamp = datetime.strptime(
                    match.group(1), "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                return self._timestamp

        except Exception as e:
            logger.error(
                f"Failed to fetch state file for sequence {self.sequence}: {e}"
            )
        return None

    @property
    def timestamp(self) -> Optional[datetime]:
        """Get the timestamp, fetching it if needed"""
        if self._timestamp is None:
            self.fetch()
        return self._timestamp
