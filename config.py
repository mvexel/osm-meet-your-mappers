"""Configuration settings for the application."""
from typing import Tuple
from dataclasses import dataclass

@dataclass
class Config:
    DB_URL: str = "postgresql://mvexel@localhost:5432/osm"
    BBOX: Tuple[float, float, float, float] = (-180, -90, 180, 90)
    REPLICATION_URL: str = "https://planet.osm.org/replication/changesets"
    CHUNK_SIZE: int = 1000
    SLEEP_INTERVAL: int = 60
