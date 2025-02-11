# OSM Changeset Loader

## Features

 - Loads changeset data from OSM archive files
 - Stores changesets, tags, and comments in PostgreSQL
 - REST API for querying changesets and mapper statistics
 - Supports filtering by:
   - Geographic bounding box
   - Time range
   - User
 - Provides mapper statistics for geographic areas

# Set up the database

## Database Initialization

1. Create a PostgreSQL database:
```bash
sudo -u postgres createdb osm_changesets
sudo -u postgres psql -c "CREATE USER osm WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE osm_changesets TO osm;"
```

2. Set the database URL in your environment:
```bash
export DATABASE_URL="postgresql://osm:your_password@localhost/osm_changesets"
```

3. Create the database tables:
```bash
/opt/osm-changeset-loader/bin/python -c "from osm_changeset_loader.db import create_tables; create_tables()"
```

## Service Installation

 # Install the package in a virtualenv
 python3 -m venv /opt/osm-changeset-loader
 /opt/osm-changeset-loader/bin/pip install -e .

 # Create system user
 sudo useradd -r -s /usr/sbin/nologin osm

 # Install service file
 sudo cp scripts/osm-changeset-loader.service /etc/systemd/system/
 sudo systemctl daemon-reload

 # Enable and start the service
 sudo systemctl enable osm-changeset-loader
 sudo systemctl start osm-changeset-loader

## API Documentation

The OSM Changeset Loader provides a REST API for querying changesets. The API is built using FastAPI and provides the following endpoint:

### GET /changesets/

Query parameters:
- `min_lon` (float): Minimum longitude for bounding box filter
- `max_lon` (float): Maximum longitude for bounding box filter  
- `min_lat` (float): Minimum latitude for bounding box filter
- `max_lat` (float): Maximum latitude for bounding box filter
- `user` (string): Filter by username
- `created_after` (datetime): Filter changesets created after this date (ISO format)
- `created_before` (datetime): Filter changesets created before this date (ISO format)
- `limit` (int): Maximum number of results to return (default: 100)
- `offset` (int): Offset for pagination (default: 0)

Example requests:
```bash
# Get first 100 changesets
curl "http://localhost:8000/changesets/"

# Get changesets within a bounding box
curl "http://localhost:8000/changesets/?min_lon=-122.5&max_lon=-122.3&min_lat=37.7&max_lat=37.8"

# Get changesets by a specific user
curl "http://localhost:8000/changesets/?user=some_user"

# Get changesets created after a specific date
curl "http://localhost:8000/changesets/?created_after=2023-01-01T00:00:00"

# Get second page of results (items 101-200)
curl "http://localhost:8000/changesets/?limit=100&offset=100"
```

Response format:
Returns a JSON array of changeset objects with the following fields:
- `id` (int): Changeset ID
- `created_at` (datetime): Creation timestamp
- `closed_at` (datetime): Closing timestamp (may be null)
- `user` (string): Username
- `uid` (int): User ID
- `min_lon`, `min_lat`, `max_lon`, `max_lat` (float): Bounding box coordinates
- `open` (bool): Whether changeset is still open

Interactive API documentation is available at:
- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/redoc (ReDoc)

 
 ## Data Loading and Synchronization Scripts

 ### Archive Loader Script

 The `archive_loader.py` script allows you to bulk import historical changeset data from OSM archive files.

 #### Usage
 ```bash
 python archive_loader.py <path_to_changeset_file.osm.bz2> <database_url>
 ```

 Optional arguments:
 - `--batch-size`: Number of records to insert in each batch (default: 50,000)
 - `--truncate`: Truncate tables before loading (default: True)
 - `--from_date`: Start date for import (YYYYMMDD format)
 - `--to_date`: End date for import (YYYYMMDD format)

 Example:
 ```bash
 python archive_loader.py changesets-230101.osm.bz2 postgresql://user:pass@localhost/osm \
     --from_date 20230101 --to_date 20230131
 ```

 ### Catch-up Script (Continuous Synchronization)

 The `catch_up.py` script continuously synchronizes your local database with the latest OpenStreetMap changeset data.

 #### Installation as a Systemd Service

 1. Create a systemd service file `/etc/systemd/system/osm-catch-up.service`:
 ```ini
 [Unit]
 Description=OSM Changeset Catch-up Service
 After=network.target postgresql.service

 [Service]
 Type=simple
 User=osm
 WorkingDirectory=/opt/osm-changeset-loader
 ExecStart=/opt/osm-changeset-loader/venv/bin/python catch_up.py
 Restart=on-failure
 RestartSec=30

 [Install]
 WantedBy=multi-user.target
 ```

 2. Enable and start the service:
 ```bash
 sudo systemctl daemon-reload
 sudo systemctl enable osm-catch-up
 sudo systemctl start osm-catch-up
 ```

 #### Configuration

 Configure the catch-up process in `osm_changeset_loader/config.py`:
 - `SLEEP_INTERVAL`: Time between checking for new changesets
 - `HISTORICAL_THREADS`: Number of threads for processing historical data

 #### Manual Execution

 You can also run the script directly:
 ```bash
 python catch_up.py
 ```

 The script will:
 - Continuously fetch and process recent changesets
 - Backfill historical data using multiple threads
 - Gracefully handle interruptions
 - Automatically restart processing if a thread completes its work

 #### Monitoring

 - Check service status: `sudo systemctl status osm-catch-up`
 - View logs: `journalctl -u osm-catch-up`

 ## Development

 Create virtual environment:
 ```bash
 python3 -m venv venv
 source venv/bin/activate
 pip install -e .
 ```

 Run tests:
 ```bash
 pytest
 ```

 Rebuild database (WARNING: deletes all data):
 ```bash
 python -c "from osm_changeset_loader.db import rebuild_database; rebuild_database()"
 ```