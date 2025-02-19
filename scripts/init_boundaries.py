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
import psycopg2

load_dotenv()

logging.basicConfig(level=logging.INFO)

DATA_URL = os.environ.get(
    "ADM_BOUNDARIES_DOWNLOAD_URL",
    "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/CGAZ/geoBoundariesCGAZ_ADM1.zip",
)
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "osmuser")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "osmpass")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "osm_db")
CONN_STR = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


def create_schema():
    """Create schema if not exists."""
    with psycopg2.connect(CONN_STR) as conn, conn.cursor() as cur:
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

    ogr_cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        CONN_STR,
        str(shp_file),
        "-a_srs",
        "EPSG:4326",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-nlt",
        "MULTIPOLYGON",
        "-nln",
        "geoboundaries.adm1",
        "-overwrite",
    ]
    logging.info("Executing command: " + " ".join(ogr_cmd))
    subprocess.run(ogr_cmd, check=True)
    logging.info("Shapefile successfully loaded into the database.")


def create_mv():
    """
    Create the materialized view for user activity centers.
    """
    with open("scripts/user_activity_centers.sql", "r") as f:
        sql = f.read()
        conn = psycopg2.connect(CONN_STR)
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
            logging.info("Initialization complete.")

        create_mv()
    except Exception as e:
        logging.exception("An error occurred during processing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
