# Set up the database

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

