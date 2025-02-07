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
- `bbox_area_km2` (float): Area of bounding box in square kilometers
- `centroid_lon`, `centroid_lat` (float): Centroid coordinates

Interactive API documentation is available at:
- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/redoc (ReDoc)

