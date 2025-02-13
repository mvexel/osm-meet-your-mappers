"""
Database convenience functions.
"""

import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """
    Get a database connection.
    """
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
    )


def truncate_tables():
    """
    Truncate all tables in the database.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE changesets, changeset_tags, changeset_comments, metadata CASCADE"
            )
            conn.commit()
            logging.info("All tables have been truncated successfully.")
    except Exception as e:
        logging.error(f"Error truncating tables: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
