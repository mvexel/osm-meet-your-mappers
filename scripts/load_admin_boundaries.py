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

load_dotenv()

logging.basicConfig(level=logging.INFO)

# Use Natural Earth Adm1 by default. If you want to use something else,
# You will need to adapt the join fields adm.admin and adm.name in the
# user_activity_centers_mv definition
DATA_URL = os.environ.get(
    "ADM_BOUNDARIES_DOWNLOAD_URL",
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip",
)


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
        "-sql",
        "SELECT admin AS name_0, name AS name_1 FROM ne_10m_admin_1_states_provinces",
        "-nln",
        "geoboundaries.adm1_boundaries",
        "-overwrite",
        str(shp_file),
    ]
    logging.debug(f"Executing command: {" ".join(ogr_cmd)}")
    subprocess.run(ogr_cmd, check=True)
    logging.info("Shapefile successfully loaded into the database.")


def main():
    try:
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

        logging.info("Boundaries loaded successfully.")
    except Exception:
        logging.exception("An error occurred during processing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
