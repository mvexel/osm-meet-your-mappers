import logging
from sqlalchemy import text
from osm_meet_your_mappers.db import get_db_session

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def truncate_tables():
    """
    Truncate all tables in the database.
    """
    session = get_db_session()
    try:
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
    finally:
        session.close()


if __name__ == "__main__":
    truncate_tables()
