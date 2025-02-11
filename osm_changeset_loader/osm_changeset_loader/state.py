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
            response = requests.get(self.url, timeout=30)
            response.raise_for_status()
            
            # Parse timestamp from state file
            # Example format: timestamp=2020-01-01T05:46:00Z
            match = re.search(r'timestamp=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)', 
                            response.text)
            if match:
                self._timestamp = datetime.strptime(
                    match.group(1), 
                    '%Y-%m-%dT%H:%M:%SZ'
                ).replace(tzinfo=timezone.utc)
                return self._timestamp
                
        except Exception as e:
            logger.error(f"Failed to fetch state file for sequence {self.sequence}: {e}")
        return None
        
    @property
    def timestamp(self) -> Optional[datetime]:
        """Get the timestamp, fetching it if needed"""
        if self._timestamp is None:
            self.fetch()
        return self._timestamp

def find_sequence_for_timestamp(
    target_time: datetime,
    start_seq: int = 1,
    end_seq: Optional[int] = None
) -> Optional[int]:
    """
    Binary search through state files to find sequence number for timestamp.
    Returns the sequence number that contains changes from the target time.
    """
    if end_seq is None:
        # Try to get the latest sequence by checking recent numbers
        test_seq = start_seq + 1_000_000  # Try 1M sequences ahead
        while True:
            state = StateFile(test_seq)
            if state.fetch():
                end_seq = test_seq
                break
            test_seq = test_seq - 100_000  # Step back if too far ahead
            if test_seq <= start_seq:
                return None
    
    while start_seq <= end_seq:
        mid_seq = (start_seq + end_seq) // 2
        state = StateFile(mid_seq)
        mid_time = state.fetch()
        
        if not mid_time:
            # If we can't fetch this state, try a nearby one
            for offset in [1, -1, 2, -2, 5, -5]:
                test_seq = mid_seq + offset
                if start_seq <= test_seq <= end_seq:
                    state = StateFile(test_seq)
                    mid_time = state.fetch()
                    if mid_time:
                        mid_seq = test_seq
                        break
            if not mid_time:
                return None
        
        if mid_time < target_time:
            start_seq = mid_seq + 1
        elif mid_time > target_time:
            end_seq = mid_seq - 1
        else:
            return mid_seq
            
    return start_seq  # Return the closest sequence
