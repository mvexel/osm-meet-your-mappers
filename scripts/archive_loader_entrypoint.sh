#!/bin/bash
set -e

# Check if input file is provided
if [ -z "$1" ]; then
  echo "Usage: docker-compose run archive_loader <input_file.osm.bz> [--from_date YYYYMMDD] [--to_date YYYYMMDD]"
  exit 1
fi

# Construct the database URL
DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo $DB_URL

# Run the archive loader with the provided arguments
python /app/scripts/archive_loader.py "/data/$1" "$DB_URL" "${@:2}"

echo "Archive loading completed successfully"
