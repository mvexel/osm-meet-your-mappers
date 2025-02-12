#!/usr/bin/env python3
import argparse
import logging
import os
from sqlalchemy import create_engine, text
from osm_meet_your_mappers.config import Config

def truncate_tables():
    """Truncate all tables in the database."""
    db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE changesets, changeset_tags, changeset_comments CASCADE;"))
        conn.commit()
        logging.info("Tables truncated successfully")

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s"
    )
    
    truncate_tables()

if __name__ == "__main__":
    main()
