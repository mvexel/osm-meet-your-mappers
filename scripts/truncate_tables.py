#!/usr/bin/env python3
import argparse
import logging
from sqlalchemy import create_engine, text
from osm_meet_your_mappers.config import Config

def truncate_tables(db_url=None):
    """Truncate all tables in the database."""
    config = Config()
    engine = create_engine(db_url or config.DB_URL)
    
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE changesets, changeset_tags, changeset_comments CASCADE;"))
        conn.commit()
        logging.info("Tables truncated successfully")

def main():
    parser = argparse.ArgumentParser(description="Truncate all tables in the database")
    parser.add_argument(
        "--db-url",
        help="Database URL (optional, will use config if not provided)",
    )
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s"
    )
    
    args = parser.parse_args()
    truncate_tables(args.db_url)

if __name__ == "__main__":
    main()
