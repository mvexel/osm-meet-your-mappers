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

2. Edit config.py to set your SQLAlchemy database URL and any other configuration you want to customize:
```python
class Config:
    DB_URL: str = "postgresql://mvexel@localhost:5432/changesets"
    BBOX: Tuple[float, float, float, float] = (-180, -90, 180, 90)
```

3. Create the database tables:
```bash
/opt/osm-meet-your-mappers/bin/python -c "from osm_meet_your_mappers.db import create_tables; create_tables()"
```

## Service Installation

 # Install the package in a virtualenv
 python3 -m venv /opt/osm-meet-your-mappers
 /opt/osm-meet-your-mappers/bin/pip install -e .

 # Create system user
 sudo useradd -r -s /usr/sbin/nologin osm

 # Install service file
 sudo cp scripts/osm-meet-your-mappers.service /etc/systemd/system/
 sudo systemctl daemon-reload

 # Enable and start the service
 sudo systemctl enable osm-meet-your-mappers
 sudo systemctl start osm-meet-your-mappers

## API Documentation

Interactive API documentation is available when you run the API at
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

 ### Continuous sync and backfill

 The `backfill.py` script continuously synchronizes your local database with the latest OpenStreetMap changeset data and backfills as needed.

 #### Installation as a Systemd Service

 1. Create a systemd service file `/etc/systemd/system/osm-catch-up.service`:
 ```ini
 [Unit]
 Description=OSM Changeset Backfill and Sync service
 After=network.target postgresql.service

 [Service]
 Type=simple
 User=osm
 WorkingDirectory=/opt/osm-meet-your-mappers
 ExecStart=/opt/osm-meet-your-mappers/venv/bin/python backfill.py
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
