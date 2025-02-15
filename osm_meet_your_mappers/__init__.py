"""OSM Changeset Loader package."""

from .api import app
from .db import get_db_connection, truncate_tables

__version__ = "1.0.1"
__all__ = [
    "app",
    "get_db_connection",
    "truncate_tables",
    "Changeset",
    "Metadata",
]

# Make the package available for direct imports
import sys
import os

package_dir = os.path.dirname(os.path.abspath(__file__))
if package_dir not in sys.path:
    sys.path.append(package_dir)
