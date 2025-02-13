"""
OpenStreetMap Changeset API

This API provides access to OpenStreetMap changeset data, allowing you to query changesets
by various parameters including geographic bounds, time ranges, and user information.

The API supports:
- Querying changesets with filtering and pagination
- Getting the oldest changeset timestamp in the database
- Retrieving mapper statistics for a geographic area
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
import os
from .db import get_db_connection
from osm_meet_your_mappers.config import Config


class ChangesetResponse(BaseModel):
    id: int
    created_at: datetime
    closed_at: Optional[datetime]
    user: str
    uid: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    open: Optional[bool]

    class Config:
        from_attributes = True


class MetadataResponse(BaseModel):
    state: str
    timestamp: datetime

    class Config:
        from_attributes = True


app = FastAPI()


# Get the directory containing this file
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")

# Mount the static directory
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# the home page
@app.get("/")
async def root():
    """Serve the main HTML page"""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get(
    "/changesets/",
    response_model=List[ChangesetResponse],
    summary="Query changesets",
    description="Retrieve OpenStreetMap changesets with optional filtering parameters.",
    response_description="List of changesets matching the query parameters",
)
async def get_changesets(
    min_lon: Optional[float] = Query(
        None,
        description="Minimum longitude of bounding box",
        example=-0.489,
        ge=-180,
        le=180,
    ),
    max_lon: Optional[float] = Query(
        None,
        description="Maximum longitude of bounding box",
        example=0.236,
        ge=-180,
        le=180,
    ),
    min_lat: Optional[float] = Query(
        None,
        description="Minimum latitude of bounding box",
        example=51.28,
        ge=-90,
        le=90,
    ),
    max_lat: Optional[float] = Query(
        None,
        description="Maximum latitude of bounding box",
        example=51.686,
        ge=-90,
        le=90,
    ),
    user: Optional[str] = Query(
        None,
        description="Filter by OpenStreetMap username",
        example="JohnDoe",
        min_length=1,
    ),
    created_after: Optional[datetime] = Query(
        None,
        description="Filter changesets created after this date (ISO format)",
        example="2024-01-01T00:00:00Z",
    ),
    created_before: Optional[datetime] = Query(
        None,
        description="Filter changesets created before this date (ISO format)",
        example="2024-02-01T00:00:00Z",
    ),
    limit: int = Query(
        100,
        description="Maximum number of results to return",
        example=100,
        ge=1,
        le=1000,
    ),
    offset: int = Query(0, description="Offset for pagination", example=0, ge=0),
):
    """
    Get changesets with optional filters.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, created_at, closed_at, user, uid, min_lon, min_lat, max_lon, max_lat, open
                FROM changesets
                WHERE (%s IS NULL OR min_lon >= %s)
                  AND (%s IS NULL OR max_lon <= %s)
                  AND (%s IS NULL OR min_lat >= %s)
                  AND (%s IS NULL OR max_lat <= %s)
                  AND (%s IS NULL OR user = %s)
                  AND (%s IS NULL OR created_at >= %s)
                  AND (%s IS NULL OR created_at <= %s)
                LIMIT %s OFFSET %s
            """
            cur.execute(query, (min_lon, min_lon, max_lon, max_lon, min_lat, min_lat, max_lat, max_lat, user, user, created_after, created_after, created_before, created_before, limit, offset))
            results = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "created_at": row[1],
                    "closed_at": row[2],
                    "user": row[3],
                    "uid": row[4],
                    "min_lon": row[5],
                    "min_lat": row[6],
                    "max_lon": row[7],
                    "max_lat": row[8],
                    "open": row[9],
                }
                for row in results
            ]
    finally:
        conn.close()


@app.get(
    "/mappers/",
    summary="Get mapper statistics",
    description="Retrieve statistics about mappers who have contributed within a specified geographic area.",
    response_description="List of mapper statistics including changeset counts and last activity",
)
async def get_mappers(
    min_lon: float = Query(
        ...,
        description="Minimum longitude of bounding box",
        example=-114.053,
        ge=-180,
        le=180,
    ),
    max_lon: float = Query(
        ...,
        description="Maximum longitude of bounding box",
        example=-109.041,
        ge=-180,
        le=180,
    ),
    min_lat: float = Query(
        ...,
        description="Minimum latitude of bounding box",
        example=36.998,
        ge=-90,
        le=90,
    ),
    max_lat: float = Query(
        ...,
        description="Maximum latitude of bounding box",
        example=42.002,
        ge=-90,
        le=90,
    ),
    min_changesets: int = Query(
        Config.MIN_CHANGESETS,
        description="Minimum number of changesets for a user",
        ge=1,
    ),
):
    """
    Retrieve all unique mappers with number of changes and date of most recent change for a bounding box.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT user, COUNT(id) AS changeset_count, MIN(created_at) AS first_change, MAX(created_at) AS last_change
                FROM changesets
                WHERE min_lon >= %s AND max_lon <= %s AND min_lat >= %s AND max_lat <= %s
                GROUP BY user
                HAVING COUNT(id) >= %s
                ORDER BY changeset_count DESC
            """
            cur.execute(query, (min_lon, max_lon, min_lat, max_lat, min_changesets))
            results = cur.fetchall()
            return [
                {
                    "user": row[0],
                    "changeset_count": row[1],
                    "first_change": row[2].isoformat(),
                    "last_change": row[3].isoformat(),
                }
                for row in results
            ]
    finally:
        conn.close()


@app.get(
    "/metadata",
    response_model=MetadataResponse,
    summary="Get replication metadata state",
    description="Returns the latest replication sequence (as stored in the Metadata table) and timestamp, indicating how far back data have been loaded.",
)
async def get_metadata():
    """
    Retrieve the replication metadata state from the database.
    This shows the lowest replication sequence number processed and its timestamp.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state, timestamp FROM metadata WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Metadata not found")
            return {"state": row[0], "timestamp": row[1]}
    finally:
        conn.close()


def main():
    """CLI entry point that starts the uvicorn server"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="OSM Meet Your Mappers - A tool to explore OpenStreetMap mapping activity"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes"
    )

    args = parser.parse_args()
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload
    )

if __name__ == "__main__":
    main()
