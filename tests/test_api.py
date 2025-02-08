import pytest
from datetime import datetime, timedelta, UTC
from fastapi.testclient import TestClient
from unittest.mock import patch
from osm_changeset_loader.api import app
from osm_changeset_loader.model import Changeset
from osm_changeset_loader.db import query_changesets, get_oldest_changeset_timestamp, get_mapper_statistics

# Constants for test data
TEST_USER = "test_user"
TEST_MIN_LON, TEST_MAX_LON = -0.5, 0.3
TEST_MIN_LAT, TEST_MAX_LAT = 51.2, 51.7
TEST_CREATED_AFTER = datetime(2024, 1, 1, tzinfo=UTC)
TEST_CREATED_BEFORE = datetime(2024, 2, 1, tzinfo=UTC)

class TestChangesetAPI:
    """Comprehensive test suite for Changeset API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Fixture to provide a test client for API testing."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_changeset(self):
        """Create a consistent mock changeset for testing."""
        return {
            'id': 123,
            'created_at': TEST_CREATED_AFTER.isoformat(),
            'closed_at': TEST_CREATED_BEFORE.isoformat(),
            'user': TEST_USER,
            'uid': 456,
            'min_lon': -0.489,
            'min_lat': 51.28,
            'max_lon': 0.236,
            'max_lat': 51.686,
            'tags': [{"key": "comment", "value": "test changeset"}],
            'comments': [],
            'open': False
        }
    
    def test_read_changesets(self, client, mock_changeset):
        """Test retrieving changesets with various query parameters."""
        with patch('osm_changeset_loader.db.query_changesets') as mock_query:
            # Arrange
            mock_query.return_value = [Changeset(**mock_changeset)]
            
            # Act
            response = client.get("/changesets/", params={
                "min_lon": TEST_MIN_LON,
                "max_lon": TEST_MAX_LON,
                "min_lat": TEST_MIN_LAT,
                "max_lat": TEST_MAX_LAT,
                "user": TEST_USER,
                "created_after": TEST_CREATED_AFTER.isoformat(),
                "created_before": TEST_CREATED_BEFORE.isoformat(),
                "limit": 10,
                "offset": 0
            })
            
            # Assert
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["user"] == TEST_USER
            
            mock_query.assert_called_once_with(
                min_lon=TEST_MIN_LON,
                max_lon=TEST_MAX_LON,
                min_lat=TEST_MIN_LAT,
                max_lat=TEST_MAX_LAT,
                user=TEST_USER,
                created_after=TEST_CREATED_AFTER,
                created_before=TEST_CREATED_BEFORE,
                limit=10,
                offset=0
            )
    
    def test_get_oldest_changeset(self, client):
        """Test retrieving the oldest changeset timestamp."""
        with patch('osm_changeset_loader.db.get_oldest_changeset_timestamp') as mock_oldest:
            # Arrange: Test with existing changeset
            test_timestamp = "2019-08-29T13:18:29"  # Matches actual API response format
            mock_oldest.return_value = test_timestamp
            
            # Act
            response = client.get("/oldest")
            
            # Assert
            assert response.status_code == 200
            assert response.json()["oldest_changeset_timestamp"] == test_timestamp
            
            # Arrange: Test with no changesets
            mock_oldest.return_value = None
            
            # Act
            response = client.get("/oldest")
            
            # Assert
            assert response.status_code == 200
            assert response.json()["oldest_changeset_timestamp"] is None
    
    def test_get_mapper_statistics(self, client):
        """Test retrieving mapper statistics."""
        with patch('osm_changeset_loader.db.get_mapper_statistics') as mock_mapper_stats:
            # Arrange
            mock_stats = [
                {
                    "user": "mapper1",
                    "changeset_count": 6,
                    "last_change": "2025-02-03T14:11:37",
                    "changeset_ids": [162216327, 162217284, 162217100, 162216663, 162216138, 162216283]
                },
                {
                    "user": "mapper2",
                    "changeset_count": 2,
                    "last_change": "2025-02-03T14:11:37",
                    "changeset_ids": [162102445, 162102165]
                }
            ]
            mock_mapper_stats.return_value = mock_stats
            
            # Act
            response = client.get("/mappers/", params={
                "min_lon": -114.053,
                "max_lon": -109.041,
                "min_lat": 36.998,
                "max_lat": 42.002
            })
            
            # Assert
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["user"] == "mapper1"
            assert data[0]["changeset_count"] == 6
            
            mock_mapper_stats.assert_called_once_with(
                min_lon=-114.053,
                max_lon=-109.041,
                min_lat=36.998,
                max_lat=42.002
            )
    
    @pytest.mark.parametrize("params,expected_error", [
        ({"min_lat": -100}, "greater than or equal to -90"),
        ({"max_lat": 100}, "less than or equal to 90"),
        ({"min_lon": -200}, "greater than or equal to -180"),
        ({"max_lon": 200}, "less than or equal to 180")
    ])
    def test_invalid_coordinate_parameters(self, client, params, expected_error):
        """Test invalid coordinate parameters with multiple scenarios."""
        response = client.get("/changesets/", params=params)
        assert response.status_code == 422
        assert expected_error in response.text.lower()
    
    def test_missing_bbox_parameters(self, client):
        """Test missing bounding box parameters for mapper statistics."""
        response = client.get("/mappers/")
        assert response.status_code == 422
        assert "required" in response.text.lower()
