"""
Meet Your Mappers API
"""

import argparse
import importlib.metadata
import os
from datetime import datetime
from typing import List, Optional

import uvicorn
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from .db import get_db_connection

# Load environment variables
load_dotenv()

# ------------------------
# OAuth Setup with Authlib
# ------------------------

app = FastAPI()

# Add session middleware (required for storing temporary credentials)
app.add_middleware(
    SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "CHANGE_ME")
)

# Initialize the OAuth instance
oauth = OAuth()
oauth.register(
    "openstreetmap",
    client_id=os.getenv("OSM_CLIENT_ID"),
    client_secret=os.getenv("OSM_CLIENT_SECRET"),
    server_metadata_url="https://www.openstreetmap.org/.well-known/openid-configuration",
    api_base_url="https://api.openstreetmap.org/api/0.6/",
    client_kwargs={"scope": "read_prefs"},
)

# ------------------------
# Static Files & Basic Endpoints
# ------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
async def health_check():
    """
    API Health Check
    """
    return {"status": "healthy"}


@app.get("/version")
async def get_version():
    """
    Get the application version
    """
    version = importlib.metadata.version("meet-your-mappers")
    return {"version": version}


@app.get("/")
async def root():
    """
    Serve index.html as static root endpoint.
    """
    return FileResponse(os.path.join(static_dir, "index.html"))


# ------------------------
# OAuth Endpoints
# ------------------------
# Login endpoint: redirect the user to the OAuth provider’s authorization page.
@app.get("/login")
async def login(request: Request):
    """
    Redirect to OSM authorization
    """
    redirect_uri = request.url_for("auth")
    # This call will store temporary credentials in the session automatically.
    return await oauth.openstreetmap.authorize_redirect(request, redirect_uri)


@app.get("/auth/check")
async def check_auth(request: Request):
    """Check if user is authenticated"""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@app.post("/logout")
async def logout(request: Request):
    """Log out the current user"""
    request.session.pop("user", None)
    return {"status": "success"}


@app.get("/auth")
async def auth(request: Request):
    """
    Get the session token and retrieve user info
    """
    token = await oauth.openstreetmap.authorize_access_token(request)
    # Await the asynchronous GET request
    resp = await oauth.openstreetmap.get("user/details.json", token=token)
    resp.raise_for_status()
    profile = (
        resp.json()
    )  # If this is also asynchronous, use: profile = await resp.json()
    if not profile:
        raise HTTPException(
            status_code=400, detail="Failed to retrieve user information"
        )
    # Store user info in session for later use
    request.session["user"] = profile
    return RedirectResponse(url="/")


# ------------------------
# Dependency to enforce authentication
# ------------------------
def get_current_user(request: Request):
    """
    Get user details from session
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


class ChangesetResponse(BaseModel):
    """
    Changeset
    """

    id: int
    created_at: datetime
    closed_at: datetime
    username: str
    uid: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    open: bool


# ------------------------
# Protected API Endpoints
# ------------------------
@app.get(
    "/changesets",
    response_model=List[ChangesetResponse],
    summary="Query changesets",
    description="Retrieve OpenStreetMap changesets with optional filtering parameters.",
    response_description="List of changesets matching the query parameters",
)
async def get_changesets(
    username: str = Query(
        ..., description="Filter by OpenStreetMap username", min_length=1
    ),
    min_lon: Optional[float] = Query(
        None, description="Minimum longitude", ge=-180, le=180
    ),
    max_lon: Optional[float] = Query(
        None, description="Maximum longitude", ge=-180, le=180
    ),
    min_lat: Optional[float] = Query(
        None, description="Minimum latitude", ge=-90, le=90
    ),
    max_lat: Optional[float] = Query(
        None, description="Maximum latitude", ge=-90, le=90
    ),
    created_after: Optional[datetime] = Query(
        None, description="Created after (ISO format)"
    ),
    created_before: Optional[datetime] = Query(
        None, description="Created before (ISO format)"
    ),
    limit: int = Query(100, description="Max number of results", ge=1, le=1000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
    current_user: dict = Depends(get_current_user),  # pylint: disable=unused-argument
):
    """
    Get changesets for a user and bbox, paginated.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
SELECT 
    id, 
    created_at, 
    closed_at, 
    username, 
    uid, 
    min_lon, 
    min_lat, 
    max_lon, 
    max_lat, 
    open
FROM 
    changesets
WHERE     
    ST_Intersects(
        ST_MakeEnvelope(%s, %s, %s, %s, 4326), 
        bbox
    )
AND (%s IS NULL OR username = %s)
AND (%s IS NULL OR created_at >= %s)
AND (%s IS NULL OR created_at <= %s)
LIMIT %s OFFSET %s;
"""
            cur.execute(
                query,
                (
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                    username,
                    username,
                    created_after,
                    created_after,
                    created_before,
                    created_before,
                    limit,
                    offset,
                ),
            )
            results = cur.fetchall()
            return [
                ChangesetResponse(
                    id=int(row[0]),
                    created_at=row[1],
                    closed_at=row[2],
                    username=row[3],
                    uid=row[4],
                    min_lon=row[5],
                    min_lat=row[6],
                    max_lon=row[7],
                    max_lat=row[8],
                    open=row[9],
                )
                for row in results
            ]
    finally:
        conn.close()


@app.get(
    "/mappers/",
    summary="Get mapper statistics",
    description="Retrieve statistics about mappers in a geographic area.",
    response_description="List of mapper statistics",
)
async def get_mappers(
    min_lon: float = Query(..., description="Minimum longitude", ge=-180, le=180),
    max_lon: float = Query(..., description="Maximum longitude", ge=-180, le=180),
    min_lat: float = Query(..., description="Minimum latitude", ge=-90, le=90),
    max_lat: float = Query(..., description="Maximum latitude", ge=-90, le=90),
    min_changesets: int = Query(
        os.getenv("MIN_CHANGESETS"), description="Minimum number of changesets", ge=1
    ),
    current_user: dict = Depends(get_current_user),  # pylint: disable=unused-argument
):
    """
    Get mappers within a bbox
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
SELECT 
    username, 
    COUNT(id) AS changeset_count, 
    MIN(created_at) AS first_change, 
    MAX(created_at) AS last_change
FROM changesets
WHERE
    max_lon - min_lon < %s AND max_lat - min_lat < %s
AND ST_Intersects(
        ST_MakeEnvelope(%s, %s, %s, %s, 4326), 
        bbox
    )
GROUP BY username
HAVING COUNT(id) >= %s
ORDER BY changeset_count DESC
            """
            cur.execute(
                query,
                (
                    os.getenv("MAX_BBOX_FOR_LOCAL", "0.1"),
                    os.getenv("MAX_BBOX_FOR_LOCAL", "0.1"),
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                    min_changesets,
                ),
            )
            results = cur.fetchall()
            return [
                {
                    "username": row[0],
                    "changeset_count": row[1],
                    "first_change": row[2].isoformat(),
                    "last_change": row[3].isoformat(),
                }
                for row in results
            ]
    finally:
        conn.close()


def main():
    """
    App entrypoint
    """
    parser = argparse.ArgumentParser(
        description="OSM Meet Your Mappers - Explore OpenStreetMap mapping activity"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)"
    )
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload on code changes"
    )

    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
