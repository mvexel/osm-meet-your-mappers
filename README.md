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
docker compose run --build --remove-orphans -v /path/to/your/file:/data archive_loader discussions-latest.osm.bz2 --from_date 20200101
```


## Run the app

```bash
docker-compose up --build -d
```