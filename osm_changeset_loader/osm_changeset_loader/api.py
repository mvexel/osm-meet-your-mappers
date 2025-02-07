"""
FastAPI implementation for changeset API.
"""

from fastapi import FastAPI, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from .model import Changeset
from .db import query_changesets


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
        orm_mode = True

app = FastAPI()


@app.get("/changesets/", response_model=List[ChangesetResponse])
async def get_changesets(
    min_lon: Optional[float] = Query(None, description="Minimum longitude"),
    max_lon: Optional[float] = Query(None, description="Maximum longitude"),
    min_lat: Optional[float] = Query(None, description="Minimum latitude"),
    max_lat: Optional[float] = Query(None, description="Maximum latitude"),
    user: Optional[str] = Query(None, description="Filter by username"),
    created_after: Optional[datetime] = Query(
        None, description="Filter changesets created after this date"
    ),
    created_before: Optional[datetime] = Query(
        None, description="Filter changesets created before this date"
    ),
    limit: int = Query(100, description="Maximum number of results to return"),
    offset: int = Query(0, description="Offset for pagination"),
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
