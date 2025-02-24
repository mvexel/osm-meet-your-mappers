# Meet Your Mappers

A web site that lets mappers find their local mapping friends.

## Configure

There are a couple places you can configure stuff...

- `.env.example` -- copy this to .env before running anything. There's comments that explain stuff. At the very least you should change the following:
   - `PG_DATA_HOST_PATH` -- make sure you have at least 100GB available here.
   - `LOADER_CHANGESET_FILE`
   - `OSM_CLIENT_ID`
   - `OSM_CLIENT_SECRET`
- `script.js` -- there is a `Config` object at the top, with comments to explain

## Initial Setup

- Download a changesets archive from [planet.osm.org](https://planet.osm.org)
- Set the path to the archive file in `.env` (LOADER_CHANGESET_FILE)
- run the initialization containers

```bash
   docker compose --profile initialization up -d
```

This will perform two actions:
1. Create the database and the schema
2. Load changeset metadata from the archive file up to `RETENTION_PERIOD` in the past.
3. Load Administrative Boundaries file for admin level 1 (state / province). This is used in the materialized view, see next step. Default is Natural Earth, see `ADM_BOUNDARIES_DOWNLOAD_URL` in `.env`
4. Create a materialized view for user activity centers (not currently used in the app)

## Regular Operation

After the initial setup, you'll need to run these services every time:

Start the database, backfill, and API:
   ```bash
   docker compose --profile production up -d
   ```

This will start three services:
1. The API itself, on port 8080
2. The backfill / catch up service, keeping the database up to date using minutely replication files from OSM
3. The PoistGIS database.


This runs:
- `db` -- PostGIS built from [the multiarch fork](https://github.com/baosystems/docker-postgis) of the official PostGIS image. You can swap out for the [official image](https://github.com/postgis/docker-postgis/actions) if it works for you, but I did not test with that.
- `backfill` -- The backfill script that takes care of populating the database. How far back it goes can be set in `.env` (see above). If you intend to go a long time back, try using the archive loader (but there's no image for that right now). The script backfills by fetching minutely changeset replication files from OSM. It also keeps an eye out for new files published every minute.
-  `api`: this exposes the FastAPI application as well as the static web site on port 8000.

If you want to run this on a public server, you will need to set up Caddy or nginx or similar to put a reverse proxy in front.

## Upgrade

If you want to upgrade the application:

1. Pull the latest from Github:
   ```bash
   git pull
   ```

2. Update dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Rebuild the docker images:
   ```bash
   docker compose down -v
   docker compose build --no-cache
   docker compose up -d
   ```

4. Check the [CHANGELOG.md](CHANGELOG.md) for any additional upgrade instructions specific to each version.
