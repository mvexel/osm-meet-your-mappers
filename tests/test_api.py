import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch
from osm_changeset_loader.api import app
from osm_changeset_loader.model import Changeset
from osm_changeset_loader.db import query_changesets, get_oldest_changeset_timestamp, get_mapper_statistics

client = TestClient(app)

@pytest.fixture
def mock_changeset():
    return Changeset(
        id=123,
        created_at=datetime.utcnow() - timedelta(days=1),
        closed_at=datetime.utcnow(),
        user="test_user",
        uid=456,
        min_lon=-0.489,
        min_lat=51.28,
        max_lon=0.236,
        max_lat=51.686,
        tags={"comment": "test changeset"},
        comments=[],
        open=False
    )

def test_read_changesets(mock_changeset):
    with patch.object(query_changesets, "__call__") as mock_query:
        mock_query.return_value = [mock_changeset]
        
        response = client.get("/changesets/", params={
            "min_lon": -0.5,
            "max_lon": 0.3,
            "min_lat": 51.2,
            "max_lat": 51.7,
            "user": "test_user",
            "created_after": "2024-01-01T00:00:00Z",
            "created_before": "2024-02-01T00:00:00Z",
            "limit": 10,
            "offset": 0
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["user"] == "test_user"
        mock_query.assert_called_once_with(
            min_lon=-0.5,
            max_lon=0.3,
            min_lat=51.2,
            max_lat=51.7,
            user="test_user",
            created_after=datetime(2024, 1, 1),
            created_before=datetime(2024, 2, 1),
            limit=10,
            offset=0
        )

def test_get_oldest_changeset():
    test_timestamp = datetime.utcnow() - timedelta(days=365)
    
    with patch.object(get_oldest_changeset_timestamp, "__call__") as mock_oldest:
        # Test with existing changeset
        mock_oldest.return_value = test_timestamp
        response = client.get("/oldest")
        assert response.status_code == 200
        assert response.json()["oldest_changeset_timestamp"] == test_timestamp.isoformat()
        
        # Test with no changesets
        mock_oldest.return_value = None
        response = client.get("/oldest")
        assert response.status_code == 200
        assert response.json()["oldest_changeset_timestamp"] is None

def test_get_mapper_statistics():
    mock_stats = [
        type("MockStat", (), {
            "user": "mapper1",
            "changeset_count": 5,
            "last_change": datetime.utcnow(),
            "changeset_ids": [1,2,3,4,5]
        }),
        type("MockStat", (), {
            "user": "mapper2",
            "changeset_count": 3,
            "last_change": datetime.utcnow() - timedelta(days=1),
            "changeset_ids": [6,7,8]
        })
    ]
    
    with patch.object(get_mapper_statistics, "__call__") as mock_mapper_stats:
        mock_mapper_stats.return_value = mock_stats
        
        response = client.get("/mappers/", params={
            "min_lon": -114.053,
            "max_lon": -109.041,
            "min_lat": 36.998,
            "max_lat": 42.002
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["user"] == "mapper1"
        assert data[1]["changeset_count"] == 3
        mock_mapper_stats.assert_called_once_with(
            min_lon=-114.053,
            max_lon=-109.041,
            min_lat=36.998,
            max_lat=42.002
        )

def test_invalid_parameters():
    # Test invalid latitude
    response = client.get("/changesets/", params={"min_lat": -100})
    assert response.status_code == 422
    assert "latitude" in response.text.lower()
    
    # Test missing bbox params for mappers endpoint
    response = client.get("/mappers/")
    assert response.status_code == 422
    assert "required" in response.text.lower()
