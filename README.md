# Meet Your Mappers

_more detail to follow..._

## Initialize the Database

To initialize the database and perform Alembic migrations, run the following command:

```bash
docker-compose up db init migrate
```

This command will set up the database and apply the necessary migrations.

## Load with an Existing OSM.bz2 Archive File

To load data from an existing OSM.bz2 archive file, use the following command:

```bash
OSM_FILE_PATH=/your/path/to/your.osm.bz2 docker-compose up loader
```

Replace `/your/path/to/your.osm.bz2` with the actual path to your OSM.bz2 file.

## Run the App and the Backfill Loader

To run the main application and the backfill loader, execute:

```bash
docker-compose up app backfill
```
