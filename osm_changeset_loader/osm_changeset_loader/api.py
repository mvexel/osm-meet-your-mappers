"""
OpenStreetMap Changeset API

This API provides access to OpenStreetMap changeset data, allowing you to query changesets
by various parameters including geographic bounds, time ranges, and user information.

The API supports:
- Querying changesets with filtering and pagination
- Getting the oldest changeset timestamp in the database
- Retrieving mapper statistics for a geographic area
"""

from fastapi import FastAPI, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from .model import Changeset
from .db import query_changesets, get_oldest_changeset_timestamp, get_mapper_statistics


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


app = FastAPI()


@app.get(
    "/changesets/",
    response_model=List[ChangesetResponse],
    summary="Query changesets",
    description="""
    Retrieve OpenStreetMap changesets with optional filtering parameters.
    
    Use this endpoint to search for changesets within specific geographic bounds,
    time ranges, or by specific users. Results are paginated for better performance.
    
    Example use cases:
    - Find all changesets in a specific city or region
    - Track recent mapping activity in an area
    - Monitor contributions from specific users
    """,
    response_description="List of changesets matching the query parameters"
)
async def get_changesets(
    min_lon: Optional[float] = Query(
        None,
        description="Minimum longitude of bounding box",
        example=-0.489,
        ge=-180,
        le=180
    ),
    max_lon: Optional[float] = Query(
        None,
        description="Maximum longitude of bounding box",
        example=0.236,
        ge=-180,
        le=180
    ),
    min_lat: Optional[float] = Query(
        None,
        description="Minimum latitude of bounding box",
        example=51.28,
        ge=-90,
        le=90
    ),
    max_lat: Optional[float] = Query(
        None,
        description="Maximum latitude of bounding box",
        example=51.686,
        ge=-90,
        le=90
    ),
    user: Optional[str] = Query(
        None,
        description="Filter by OpenStreetMap username",
        example="JohnDoe",
        min_length=1
    ),
    created_after: Optional[datetime] = Query(
        None,
        description="Filter changesets created after this date (ISO format)",
        example="2024-01-01T00:00:00Z"
    ),
    created_before: Optional[datetime] = Query(
        None,
        description="Filter changesets created before this date (ISO format)",
        example="2024-02-01T00:00:00Z"
    ),
    limit: int = Query(
        100,
        description="Maximum number of results to return",
        example=100,
        ge=1,
        le=1000
    ),
    offset: int = Query(
        0,
        description="Offset for pagination",
        example=0,
        ge=0
    ),
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
    description="""
    Retrieve the timestamp of the oldest changeset stored in the database.
    
    This endpoint is useful for:
    - Determining the temporal coverage of the database
    - Checking when data collection began
    - Planning historical analysis
    """,
    response_description="Timestamp of the oldest changeset in ISO format"
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
    description="""
    Retrieve statistics about mappers who have contributed within a specified geographic area.
    
    This endpoint provides insights into:
    - Who is actively mapping in an area
    - How many changesets each mapper has contributed
    - When each mapper last made changes
    
    The bounding box parameters are required to limit the geographic scope of the query.
    """,
    response_description="List of mapper statistics including changeset counts and last activity"
)
async def get_mappers(
    min_lon: float = Query(
        ...,
        description="Minimum longitude of bounding box",
        example=-0.489,
        ge=-180,
        le=180
    ),
    max_lon: float = Query(
        ...,
        description="Maximum longitude of bounding box",
        example=0.236,
        ge=-180,
        le=180
    ),
    min_lat: float = Query(
        ...,
        description="Minimum latitude of bounding box",
        example=51.28,
        ge=-90,
        le=90
    ),
    max_lat: float = Query(
        ...,
        description="Maximum latitude of bounding box",
        example=51.686,
        ge=-90,
        le=90
    )
):
    """
    Retrieve all unique mappers with number of changes and date of most recent change for a bounding box.
    """
    mapper_stats = get_mapper_statistics(min_lon, max_lon, min_lat, max_lat)
    return [
        {
            "user": stat.user,
            "changeset_count": stat.changeset_count,
            "last_change": stat.last_change.isoformat()
        }
        for stat in mapper_stats
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
