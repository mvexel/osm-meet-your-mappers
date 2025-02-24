#!/usr/bin/env python3
import os
import sys
import logging
import zipfile
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv
import requests
from osm_meet_your_mappers.db import get_db_connection

load_dotenv()

logging.basicConfig(level=logging.INFO)

# Use Natural Earth Adm1 by default. If you want to use something else,
# You will need to adapt the join fields adm.admin and adm.name in the
# user_activity_centers_mv definition (see user_activity_centers.sql)
DATA_URL = os.environ.get(
    "ADM_BOUNDARIES_DOWNLOAD_URL",
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip",
)


def create_schema():
    """Create schema if not exists."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS geoboundaries;")


def download_file(url: str, local_path: Path, timeout: int = 10):
    if local_path.exists():
        logging.info(f"File {local_path} already exists. Skipping download.")
        return
    logging.info(f"Downloading {url}...")
    response = requests.get(url, stream=True, timeout=timeout)
    response.raise_for_status()
    with local_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    logging.info(f"Downloaded file saved to {local_path}.")


def unzip_file(zip_path: Path, extract_to: Path):
    logging.info(f"Extracting {zip_path} to {extract_to}...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_to)
    logging.info("Extraction complete.")


def load_shapefile(extract_path: Path):
    # Look for the .shp file in the extracted directory
    shp_files = list(extract_path.glob("*.shp"))
    if not shp_files:
        raise RuntimeError("No shapefile (.shp) found in the extracted directory.")
    shp_file = shp_files[0]
    logging.info(f"Found shapefile: {shp_file}")

    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_user = os.environ.get("POSTGRES_USER", "osmuser")
    pg_password = os.environ.get("POSTGRES_PASSWORD", "osmpass")
    pg_dbname = os.environ.get("POSTGRES_DB", "osm_db")
    dsn = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_dbname}"

    ogr_cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        dsn,
        "-a_srs",
        "EPSG:4326",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-nlt",
        "MULTIPOLYGON",
        "-nln",
        "geoboundaries.adm1",
        "-overwrite",
        str(shp_file),
    ]
    logging.debug(f"Executing command: {" ".join(ogr_cmd)}")
    subprocess.run(ogr_cmd, check=True)
    logging.info("Shapefile successfully loaded into the database.")


def create_mv():
    """
    Create the materialized view for user activity centers.
    """
    with open("scripts/user_activity_centers.sql", "r") as f:
        sql = f.read()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        cursor.close()
        conn.close()
    logging.info("Materialized view created successfully.")


def main():
    try:
        create_schema()

        # Use a temporary directory for download and extraction
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            zip_path = tmp_path / "geoboundaries.zip"
            extract_path = tmp_path / "geoboundaries"
            extract_path.mkdir(exist_ok=True)

            download_file(DATA_URL, zip_path)
            unzip_file(zip_path, extract_path)
            load_shapefile(extract_path)
            logging.info("Geo boundaty load complete.")

        create_mv()
        logging.info("Materialized view created successfully.")
    except Exception as e:
        logging.exception("An error occurred during processing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
