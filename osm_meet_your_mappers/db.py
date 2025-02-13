"""
Database convenience functions.
"""

import logging
from typing import List, Optional
from sqlalchemy import create_engine, and_, func, text
from sqlalchemy.orm import Session
from sqlalchemy_utils import database_exists, drop_database, create_database
from .model import Changeset, ChangesetComment, ChangesetTag, Metadata, Base
from osm_meet_your_mappers.config import Config

config = Config()


def get_db_engine(db_url=None):
    """
    Get a database engine.
    """
    if db_url is None:
        db_url = config.DB_URL
    return create_engine(db_url)


def get_db_session(db_url=None):
    """
    Get a database session.
    """
    if db_url is None:
        db_url = config.DB_URL
    engine = get_db_engine(db_url)
    return Session(engine)


def create_tables(db_url=None):
    """
    Create database tables.
    """
    if db_url is None:
        db_url = config.DB_URL
    engine = get_db_engine(db_url)
    Changeset.__table__.create(engine, checkfirst=True)
    ChangesetComment.__table__.create(engine, checkfirst=True)
    ChangesetTag.__table__.create(engine, checkfirst=True)
    Metadata.__table__.create(engine, checkfirst=True)


def query_changesets(
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    user: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Changeset]:
    """
    Query changesets with optional filters.
    """
    session = get_db_session()

    query = session.query(Changeset)

    # Bounding box filter
    if all([min_lon, max_lon, min_lat, max_lat]):
        query = query.filter(
            and_(
                Changeset.min_lon >= min_lon,
                Changeset.max_lon <= max_lon,
                Changeset.min_lat >= min_lat,
                Changeset.max_lat <= max_lat,
            )
        )

    # User filter
    if user:
        query = query.filter(Changeset.user == user)

    # Date range filters
    if created_after:
        query = query.filter(Changeset.created_at >= created_after)
    if created_before:
        query = query.filter(Changeset.created_at <= created_before)

    return query.offset(offset).limit(limit).all()


def get_mapper_statistics(
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
    min_changesets: int,
    db_url=None,
):
    if db_url is None:
        db_url = Config().DB_URL
    """
    Get mapper statistics within a bounding box.
    Only counts changesets whose bounding boxes are completely contained within
    the query bounding box.

    Args:
        min_lon: Minimum longitude of bounding box
        max_lon: Maximum longitude of bounding box
        min_lat: Minimum latitude of bounding box
        max_lat: Maximum latitude of bounding box
        db_url: Database connection URL
    """
    session = get_db_session(db_url)
    query_box = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    return (
        session.query(
            Changeset.user,
            func.count(Changeset.id).label("changeset_count"),
            func.min(Changeset.created_at).label("first_change"),
            func.max(Changeset.created_at).label("last_change"),
        )
        .filter(func.ST_Within(Changeset.bbox, query_box))
        .group_by(Changeset.user)
        .having(func.count(Changeset.id) >= min_changesets)
        .order_by(func.count(Changeset.id).desc())
        .all()
    )


def truncate_tables(check_exist=True):
    """
    Truncate all tables in the database.

    Args:
        check_exist (bool): If True, check if tables exist before truncating
    """
    session = get_db_session()
    try:
        if check_exist:
            # Check if tables exist
            tables_exist = session.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'changesets')"
                )
            ).scalar()
            if not tables_exist:
                logging.warning("Tables do not exist - skipping truncation")
                return

        # Disable foreign key checks
        session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

        # Truncate tables
        session.execute(text("TRUNCATE TABLE changesets CASCADE"))
        session.execute(text("TRUNCATE TABLE changeset_tags CASCADE"))
        session.execute(text("TRUNCATE TABLE changeset_comments CASCADE"))
        session.execute(text("TRUNCATE TABLE metadata CASCADE"))

        # Re-enable foreign key checks
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        session.commit()
        logging.info("All tables have been truncated successfully.")
    except Exception as e:
        logging.error(f"Error truncating tables: {e}")
        session.rollback()
        raise
    finally:
        session.close()
    """
    Create the database and add the PostGIS extension.
    """
    if db_url is None:
        db_url = config.DB_URL

    # Create database if it doesn't exist
    if not database_exists(db_url):
        create_database(db_url)

    # Connect to database and create PostGIS extension
    engine = get_db_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()


def truncate_tables(check_exist=True):
    """
    Truncate all tables in the database.

    Args:
        check_exist (bool): If True, check if tables exist before truncating
    """
    session = get_db_session()
    try:
        if check_exist:
            # Check if tables exist
            tables_exist = session.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'changesets')"
                )
            ).scalar()
            if not tables_exist:
                logging.warning("Tables do not exist - skipping truncation")
                return

        # Disable foreign key checks
        session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

        # Truncate tables
        session.execute(text("TRUNCATE TABLE changesets CASCADE"))
        session.execute(text("TRUNCATE TABLE changeset_tags CASCADE"))
        session.execute(text("TRUNCATE TABLE changeset_comments CASCADE"))
        session.execute(text("TRUNCATE TABLE metadata CASCADE"))

        # Re-enable foreign key checks
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        session.commit()
        logging.info("All tables have been truncated successfully.")
    except Exception as e:
        logging.error(f"Error truncating tables: {e}")
        session.rollback()
        raise
    finally:
        session.close()
    if db_url is None:
        db_url = Config().DB_URL
    """
    Drop and recreate the entire database, then create all tables.

    WARNING: This will delete all existing data in the database!
    """
    engine = get_db_engine(db_url)

    # Drop the database if it exists
    if database_exists(db_url):
        drop_database(db_url)

    # Create the database
    create_database(db_url)

    # Create all tables defined in the Base metadata
    Base.metadata.create_all(engine)
