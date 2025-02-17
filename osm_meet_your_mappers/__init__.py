"""OSM Changeset Loader package."""

from .api import app
from .db import get_db_connection, truncate_tables

# Retrieve the version from installed package metadata
from importlib.metadata import version as get_version

__version__ = get_version("meet-your-mappers")

__all__ = [
    "app",
    "get_db_connection",
    "truncate_tables",
    "Changeset",
    "Metadata",
]
