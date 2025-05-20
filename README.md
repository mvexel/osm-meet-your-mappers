# Meet Your Mappers

## We are on Sourcehut
If you are reading this notice on Github, please point your bookmarks and git remotes at the `meetyourmappers` repo [on Sourcehut](https://git.sr.ht/~mvexel/meetyourmappers) instead. This project will not be updated on Github.

---

A web site and API that lets mappers find their local mapping friends.

---

## 1. Prerequisites

1. **Clone or download this repository.**  
2. **Copy `.env.example` to `.env`.**  
   - Update the values in `.env`:
     - `PG_DATA_HOST_PATH` must point to a directory with **at least 100GB** of free space (for Postgres data).
     - `LOADER_CHANGESET_FILE` must point to the downloaded changesets archive (`.osm.bz2`).
     - `OSM_CLIENT_ID` and `OSM_CLIENT_SECRET` must be replaced with your OSM OAuth credentials.

3. **Optionally**, edit the `Config` object in `script.js` if you need different client-side settings.

---

## 2. Download Changesets Archive

1. **Obtain the changeset archive** (e.g., from [https://planet.osm.org](https://planet.osm.org))—the `.osm.bz2` file.
2. **Set** the path to this file as `LOADER_CHANGESET_FILE` in your `.env`.

---

## 3. Initial Database Setup

1. **Spin up the initialization services:**

   ```bash
   docker compose --profile initialization up -d
   ```
   
2. This performs the following:
   1. Creates the database (and schema).
   2. Loads changeset metadata from your archive up to `RETENTION_DAYS` in the past.
   3. Downloads & loads administrative boundaries (default is Natural Earth, see `ADM_BOUNDARIES_DOWNLOAD_URL` in `.env`).
   4. Creates a materialized view for user activity centers (not currently used in the app).

> **Warning:** This process truncates the changeset tables—be sure you’re okay with dropping and reloading existing data.

---

## 4. Regular Operation

1. **Start the main services** (database, backfill, and API) with:
   ```bash
   docker compose --profile production up -d
   ```

2. This runs:
   - **`db`**: A PostGIS database (using a multi-arch PostGIS Dockerfile).  
   - **`backfill`**: Keeps the database up-to-date with minutely replication files from OSM.  
   - **`api`**: Exposes the FastAPI application and static site on port `8000`.  

3. If you want the site publicly accessible, put a reverse proxy (e.g., Caddy, nginx) in front of `0.0.0.0:8000`.

---

## 5. Upgrading

1. **Pull latest code from Git**:
   ```bash
   git pull
   ```

2. Check `setup_db.sql` for changes since your currently running version and apply them.

3. **Rebuild the Docker images**:
   ```bash
   docker compose --profile production up --build -d
   ```
---

## 6. Summary of Key Environment Variables

Below are some critical settings you might need to tweak in `.env`:

- **`PG_DATA_HOST_PATH`**: Host directory mapped for Postgres data; must have ample disk space.  
- **`LOADER_CHANGESET_FILE`**: Path to the `.osm.bz2` changeset archive file.  
- **`OSM_CLIENT_ID` / `OSM_CLIENT_SECRET`**: OSM OAuth credentials.  
- **`RETENTION_DAYS`**: How many days in the past to load from changesets.  
- **`START_SEQUENCE`**: Which replication sequence to start from (for historical backfill).  
- **`MIN_CHANGESETS`**, **`MAX_BBOX_FOR_LOCAL`**, etc.: Adjusts how user activity is filtered.  