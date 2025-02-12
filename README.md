# Meet Your Mappers

_more detail to follow..._

## Initial load of DB

Grab a changesets or changesets+discussions archive from planet.osm.org. 

Edit `docker-compose.yaml` to set the path to your PG data. This needs to have 100GB of space at least. 150 is better.

```
    volumes:
      - /your/local/postgresql/data:/var/lib/postgresql/data
```

Then run the loader.


```bash
> OSM_FILE_PATH=/your/path/to/discussions-250203.osm.bz2 LOADER_ARGS="--from_date=20200101" docker compose -f docker-compose.init.yaml up --build
```

wait a while.... (hours)

## Run the app

```bash
docker-compose up --build -d
```