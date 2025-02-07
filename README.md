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
/opt/osm-changeset-parser/bin/python -c "from osm_changeset_parser.db import create_tables; create_tables()"
```

## Service Installation

 # Install the package in a virtualenv
 python3 -m venv /opt/osm-changeset-parser
 /opt/osm-changeset-parser/bin/pip install -e .

 # Create system user
 sudo useradd -r -s /usr/sbin/nologin osm

 # Install service file
 sudo cp scripts/osm-changeset-parser.service /etc/systemd/system/
 sudo systemctl daemon-reload

 # Enable and start the service
 sudo systemctl enable osm-changeset-parser
 sudo systemctl start osm-changeset-parser

