import os
import sys
from typing import Dict


class ConfigurationError(Exception):
    """Raised when there's an error in configuration."""

    pass


def get_env_config() -> Dict:
    """Load configuration from environment variables."""
    try:
        config = {
            "num_workers": int(os.getenv("LOADER_NUM_WORKERS", "4")),
            "queue_size": int(os.getenv("LOADER_QUEUE_SIZE", "1000")),
            "batch_size": int(os.getenv("LOADER_BATCH_SIZE", "50000")),
            "retention_days": int(os.getenv("RETENTION_DAYS", "365")),
            "log_level": os.getenv("LOGLEVEL", "INFO").upper(),
            "changeset_file": os.getenv("LOADER_CHANGESET_FILE"),
            "buffer_size": int(os.getenv("LOADER_BUFFER_SIZE", "262144")),
            "start_sequence": int(os.getenv("START_SEQUENCE", "0")),
        }
        return config
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration: {e}")


def validate_config(config: Dict) -> None:
    current_script = os.path.basename(sys.argv[0])  # only needed for archive loader.

    if current_script in ["archive_loader.py"]:
        if not config["changeset_file"]:
            raise ConfigurationError("LOADER_CHANGESET_FILE is not set.")
        if not os.path.exists(config["changeset_file"]):
            raise ConfigurationError(
                f"Changeset file not found: {config['changeset_file']}"
            )
