"""Configuration settings for the application."""

from typing import Tuple
from dataclasses import dataclass


@dataclass
class Config:
    DB_URL: str = "postgresql://mvexel@localhost:5432/changesets"
    BBOX: Tuple[float, float, float, float] = (-180, -90, 180, 90)
    MIN_CHANGESETS = 1  # minimum number of changesets for a mapper to be included
