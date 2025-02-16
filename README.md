# Meet Your Mappers

A web site that lets mappers find their local mapping friends.

## Configure

There are a couple places you can configure stuff...

- `.env.example` -- copy this to .env before running anything. There's comments that explain stuff.
- `docker-compose.yml` -- only thing you MUST change is the path mapping to the postgresql data dir. If you plan on running this with all changesets going back to the beginning of time, make sure you have at least 100GB of space on this path, 150GB is probably better.
- `script.js` -- there is a `Config` object at the top, with comments to explain

## Run

1. Install Poetry if you haven't already:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Install docker
4. Configure as outlined above
5. Start the services:
   ```bash
   docker compose up -d
   ```

This builds and launches 3 docker images:
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
   poetry install
   ```

3. Rebuild the docker images:
   ```bash
   docker compose down -v
   docker compose build --no-cache
   docker compose up -d
   ```

4. Check the [CHANGELOG.md](CHANGELOG.md) for any additional upgrade instructions specific to each version.
