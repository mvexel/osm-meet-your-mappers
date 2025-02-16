"""OSM Changeset Loader package."""

import tomli
from pathlib import Path

from .api import app
from .db import get_db_connection, truncate_tables

# Read version from pyproject.toml
with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
    __version__ = tomli.load(f)["tool"]["poetry"]["version"]
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
