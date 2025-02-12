#!/usr/bin/env python3
import sys
from osm_meet_your_mappers.db import rebuild_database


def main():
    """
    CLI entrypoint for rebuilding the database.
    Allows optional database URL as an argument.
    """
    db_url = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        if db_url:
            rebuild_database(db_url)
        else:
            rebuild_database()
        print("Database successfully rebuilt.")
    except Exception as e:
        print(f"Error rebuilding database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
