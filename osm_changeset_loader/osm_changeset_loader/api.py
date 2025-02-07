"""
FastAPI implementation for changeset API.
"""

from fastapi import FastAPI, Query
from typing import Optional, List
from datetime import datetime
from .model import Changeset
from .db import query_changesets

app = FastAPI()


@app.get("/changesets/")
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
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
