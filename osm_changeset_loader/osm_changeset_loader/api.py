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
from .model import Changeset, Metadata
from .db import query_changesets, get_oldest_changeset_timestamp, get_mapper_statistics
from .config import Config


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
    bbox_area_km2: float
    centroid_lon: float
    centroid_lat: float

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
    return query_changesets(
        min_lon=min_lon,
        max_lon=max_lon,
        min_lat=min_lat,
        max_lat=max_lat,
        user=user,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/oldest",
    summary="Get oldest changeset timestamp",
    description="Retrieve the timestamp of the oldest changeset stored in the database.",
    response_description="Timestamp of the oldest changeset in ISO format",
)
async def get_oldest_changeset():
    """
    Get the timestamp of the oldest changeset in the database.
    Returns:
        dict: Dictionary with the oldest changeset timestamp or null if no changesets exist
    """
    timestamp = get_oldest_changeset_timestamp()
    return {"oldest_changeset_timestamp": timestamp.isoformat() if timestamp else None}


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
    mapper_stats = get_mapper_statistics(
        min_lon, max_lon, min_lat, max_lat, min_changesets
    )
    return [
        {
            "user": stat.user,
            "changeset_count": stat.changeset_count,
            "first_change": stat.first_change.isoformat(),
            "last_change": stat.last_change.isoformat(),
        }
        for stat in mapper_stats
    ]


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
    from .db import get_db_session

    db = get_db_session()
    try:
        meta = db.query(Metadata).filter(Metadata.id == 1).first()
        if meta is None:
            raise HTTPException(status_code=404, detail="Metadata not found")
        return meta
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
