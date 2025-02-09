import logging
import signal
import time
from contextlib import contextmanager

from osm_changeset_loader.config import Config
from osm_changeset_loader.db import get_db_session
from osm_changeset_loader.model import Changeset
from osm_changeset_loader.replication import ReplicationClient

# Configuration
config = Config()
replication_client = ReplicationClient(config)
POLL_INTERVAL = 30  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

@contextmanager
def session_scope():
    session = get_db_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def insert_changesets_bulk(changesets) -> bool:
    """Bulk insert or update changesets to optimize database performance."""
    try:
        with session_scope() as session:
            for cs in changesets:
                session.merge(cs)
        return True
    except Exception as e:
        logging.error(f"Error inserting changesets: {e}")
        return False

def process_latest():
    """Process the most recent changeset sequence."""
    try:
        current = replication_client.get_remote_state()
        if current:
            logging.info(f"Processing sequence {current.sequence}")
            changesets = replication_client.get_changesets(current)
            if changesets:
                return insert_changesets_bulk(changesets)
    except Exception as e:
        logging.error(f"Error processing latest sequence: {e}")
    return False

def run_daemon():
    """Run the daemon process that polls for new changes."""
    stop = False
    
    def handle_signal(signum, frame):
        nonlocal stop
        stop = True
        logging.info("Received stop signal, finishing up...")
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    logging.info("Starting recent changes daemon...")
    
    while not stop:
        try:
            process_latest()
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            time.sleep(POLL_INTERVAL)
    
    logging.info("Daemon stopped.")

if __name__ == "__main__":
    run_daemon()
