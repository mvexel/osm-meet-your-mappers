# Meet Your Mappers

_more detail to follow..._

## Configure

There are a couple places you can configure stuff...

- `.env.example` -- copy this to .env before running anything. There's comments that explain stuff.
- `docker-compose.yml` -- only thing you MUST change is the path mapping to the postgresql data dir. If you plan on running this with all changesets going back to the beginning of time, make sure you have at least 100GB of space on this path, 150GB is probably better.
- `script.js` -- there is a `Config` object at the top, with comments to explain

## Run

- Install docker
- Configure as outlined above
- `docker compose up -d

This builds and launches 3 docker images:
- `osm-changeset-loader-db-1` -- PostGIS built from [the multiarch fork](https://github.com/baosystems/docker-postgis) of the official PostGIS image. You can swap out for the [official image](https://github.com/postgis/docker-postgis/actions) if it works for you, but I did not test with that.
- `osm-changeset-loader-backfill-1` -- The backfill script that takes care of populating the database. How far back it goes can be set in `.env` (see above). If you intend to go a long time back, try using the archive loader (but there's no image for that right now). The script backfills by fetching minutely changeset replication files from OSM. It also keeps an eye out for new files published every minute.
-  `osm-changeset-loader-api-1`: this exposes the FastAPI application as well as the static web site on port 8000.

If you want to run this on a public server, you will need to set up Caddy or nginx or similar to put a reverse proxy in front.
