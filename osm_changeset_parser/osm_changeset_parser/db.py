"""
Database convenience functions.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from model import Changeset, Metadata

DB_URL = "postgresql://mvexel@localhost:5432/osm"


def get_db_engine(db_url=DB_URL):
    """
    Get a database engine.
    """
    return create_engine(db_url)


def get_db_session(db_url=DB_URL):
    """
    Get a database session.
    """
    engine = get_db_engine(db_url)
    return Session(engine)


def create_tables(db_url=DB_URL):
    """
    Create database tables.
    """
    engine = get_db_engine(db_url)
    Metadata.__table__.create(engine, checkfirst=True)
    Changeset.__table__.create(engine, checkfirst=True)
