import logging
import signal
import threading
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import get_db_session, get_last_processed_sequence
from osm_changeset_loader.model import Metadata, Changeset
from osm_changeset_loader.path import Path
from osm_changeset_loader.replication import ReplicationClient

# Configuration
config = Config()
replication_client = ReplicationClient(config)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class SyncDaemon:
    def __init__(self):
        self.stop_event = threading.Event()
        self.backfill_thread = None
        self.forward_sync_thread = None
        logger.debug("SyncDaemon initialized")
        
    def update_metadata(self, session: Session, sequence: int, success: bool = True) -> None:
        """Update metadata with the latest processed state"""
        try:
            metadata = Metadata(
                timestamp=datetime.utcnow(),
                state=f"sequence:{sequence}:{'success' if success else 'failed'}"
            )
            session.add(metadata)
            session.commit()
            logger.debug(f"Updated metadata for sequence {sequence} (success={success})")
        except Exception as e:
            logger.error(f"Failed to update metadata for sequence {sequence}: {e}")
            session.rollback()

    def process_sequence(self, sequence: int, session: Session) -> bool:
        """Process a single replication sequence"""
        try:
            current_path = Path(sequence=sequence)
            logger.info(f"Processing sequence {sequence}")
            
            changesets = replication_client.get_changesets(current_path)
            if not changesets:
                return False
                
            for cs in changesets:
                existing = session.query(Changeset).filter(Changeset.id == cs.id).first()
                if existing:
                    return False  # We've reached an existing changeset, stop processing
                session.add(cs)
            
            self.update_metadata(session, sequence)
            session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error processing sequence {sequence}: {e}")
            self.update_metadata(session, sequence, success=False)
            session.rollback()
            return False

    def backfill_worker(self):
        """Work backwards from current state until reaching existing data"""
        logger.debug("Backfill worker started")
        session = get_db_session()
        try:
            remote_state = replication_client.get_remote_state()
            if not remote_state:
                logger.error("Could not get remote state")
                return

            current_sequence = remote_state.sequence
            logger.info(f"Starting backfill from sequence {current_sequence}")

            for sequence in range(current_sequence, 0, -1):
                if self.stop_event.is_set():
                    logger.debug("Stop event set, breaking backfill loop")
                    break

                logger.debug(f"Processing sequence {sequence}")
                if not self.process_sequence(sequence, session):
                    logger.info(f"Reached already processed sequence {sequence}, stopping backfill")
                    break

                time.sleep(0.1)  # Rate limiting

        except Exception as e:
            logger.error(f"Error in backfill worker: {e}")
        finally:
            session.close()
            logger.debug("Backfill worker finished")

    def forward_sync_worker(self):
        """Check for new changes and process them"""
        logger.debug("Forward sync worker started")
        session = get_db_session()
        try:
            while not self.stop_event.is_set():
                try:
                    logger.debug("Fetching remote state")
                    remote_state = replication_client.get_remote_state()
                    if not remote_state:
                        logger.warning("Could not fetch remote state")
                        time.sleep(60)
                        continue

                    remote_sequence = remote_state.sequence
                    last_processed = get_last_processed_sequence()
                    logger.debug(f"Remote sequence: {remote_sequence}, Last processed: {last_processed}")

                    if remote_sequence > last_processed:
                        logger.info(f"New sequences available: {last_processed+1} to {remote_sequence}")
                        for sequence in range(last_processed + 1, remote_sequence + 1):
                            if self.stop_event.is_set():
                                logger.debug("Stop event set, breaking forward sync loop")
                                break
                            self.process_sequence(sequence, session)
                    else:
                        logger.debug(f"No new sequences available (current={remote_sequence}, last_processed={last_processed})")

                    logger.debug("Sleeping for 60 seconds")
                    time.sleep(60)  # Check every minute

                except Exception as e:
                    logger.error(f"Error in forward sync: {e}")
                    time.sleep(30)

        finally:
            session.close()
            logger.debug("Forward sync worker finished")

    def start(self):
        """Start the sync daemon threads"""
        logger.info("Starting sync daemon")
        
        # Start backfill thread
        self.backfill_thread = threading.Thread(target=self.backfill_worker)
        self.backfill_thread.start()
        
        # Start forward sync thread
        self.forward_sync_thread = threading.Thread(target=self.forward_sync_worker)
        self.forward_sync_thread.start()

    def stop(self):
        """Stop the sync daemon threads"""
        logger.info("Stopping sync daemon")
        self.stop_event.set()
        
        if self.backfill_thread:
            self.backfill_thread.join()
        if self.forward_sync_thread:
            self.forward_sync_thread.join()

def main():
    daemon = SyncDaemon()
    
    def signal_handler(signum, frame):
        daemon.stop()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        daemon.start()
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()

if __name__ == "__main__":
    main()
