"""
Database convenience functions.
"""

import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """Get database connection with proper timeout settings."""
    conn_params = {
        "dbname": os.getenv("POSTGRES_DB"),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "host": os.getenv("POSTGRES_HOST"),
        "port": os.getenv("POSTGRES_PORT"),
        "connect_timeout": 30,  # Connection timeout in seconds
        "options": "-c statement_timeout=300000",  # Query timeout in milliseconds (5 min)
    }

    try:
        conn = psycopg2.connect(**conn_params)
        # Set session parameters
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '300s'")  # 5 minutes
        conn.commit()
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Failed to connect to database: {e}")
        raise
