import os
from typing import Tuple
from dataclasses import dataclass


@dataclass
class Config:
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_USER: str = os.getenv("DB_USER", "mvexel")
    DB_PASS: str = os.getenv("DB_PASS", "")  # empty password by default
    DB_NAME: str = os.getenv("DB_NAME", "changesets2")

    @property
    def DB_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    BBOX: Tuple[float, float, float, float] = (-180, -90, 180, 90)
    MIN_CHANGESETS: int = 1  # minimum number of changesets for a mapper to be included
    SLEEP_TIME: int = int(
        os.getenv("SLEEP_TIME", 300)
    )  # sleep time between catch up attempts when we're done backfilling
    MIN_SEQ: int = int(
        os.getenv("MIN_SEQ", 0)
    )  # Work back to this sequence when backfilling
    BLOCK_SIZE: int = int(
        os.getenv("BLOCK_SIZE", 10)
    )  # Number of processes for changeset backfill and catch up
    BATCH_SIZE: int = int(
        os.getenv("BATCH_SIZE", 50_000)
    )  # number of changesets to insert in a batch
