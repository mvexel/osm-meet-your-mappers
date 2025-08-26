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

# Check if authentication is enabled
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"

# ------------------------
# OAuth Setup with Authlib
# ------------------------

app = FastAPI()

# Add session middleware (required for storing temporary credentials when auth is enabled)
if AUTH_ENABLED:
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SESSION_SECRET", "CHANGE_ME"),
        https_only=True,  # ensures cookie is only sent over HTTPS
        same_site="lax",  # "lax" is usually fine for OAuth
    )

# Initialize the OAuth instance only if auth is enabled
oauth = None
if AUTH_ENABLED:
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


@app.get("/latest")
async def get_latest():
    """
    Get the timestamp for the latest changeset in the database
    """
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(closed_at) FROM changesets")
            result = cur.fetchone()
            latest_timestamp = result[0].isoformat() if result[0] else None
            return {"latest_timestamp": latest_timestamp}
    finally:
        conn.close()


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
    if not AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    redirect_uri = request.url_for("auth")
    # This call will store temporary credentials in the session automatically.
    return await oauth.openstreetmap.authorize_redirect(request, redirect_uri)


@app.get("/auth/check")
async def check_auth(request: Request):
    """Check if user is authenticated"""
    if not AUTH_ENABLED:
        return {"user": {"display_name": "Anonymous"}, "auth_enabled": False}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@app.post("/logout")
async def logout(request: Request):
    """Log out the current user"""
    if not AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    request.session.pop("user", None)
    return {"status": "success"}


@app.get("/auth")
async def auth(request: Request):
    """
    Get the session token and retrieve user info
    """
    if not AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
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
    if not AUTH_ENABLED:
        return {"user": {"display_name": "Anonymous"}, "auth_enabled": False}
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
    ST_XMin(bbox) as min_lon,
    ST_YMin(bbox) as min_lat,
    ST_XMax(bbox) as max_lon,
    ST_YMax(bbox) as max_lat,
    open
FROM 
    changesets
WHERE 
    (%s IS NULL OR username = %s)
AND (%s IS NULL OR created_at >= %s)
AND (%s IS NULL OR created_at <= %s)
"""
            params = [
                username,
                username,
                created_after,
                created_after,
                created_before,
                created_before,
            ]

            # Only add bbox filter if coordinates are provided
            if all(coord is not None for coord in [min_lon, min_lat, max_lon, max_lat]):
                query += """
AND ST_Intersects(
    ST_MakeEnvelope(%s, %s, %s, %s, 4326), 
    bbox
)
"""
                params.extend([min_lon, min_lat, max_lon, max_lat])

            query += "LIMIT %s OFFSET %s;"
            params.extend([limit, offset])

            cur.execute(query, params)
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
    polygon: Optional[str] = Query(None, description="Polygon in WKT format"),
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
    (ST_XMax(bbox) - ST_XMin(bbox)) < %s AND (ST_YMax(bbox) - ST_YMin(bbox)) < %s
AND (
    CASE
        WHEN %s IS NOT NULL THEN ST_Intersects(bbox, ST_SetSRID(ST_GeomFromText(%s), 4326))
        ELSE ST_Intersects(bbox, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
    END
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
                    polygon,
                    polygon,
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
                    "first_change": row[2].isoformat() if row[2] else None,
                    "last_change": row[3].isoformat() if row[3] else None,
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
