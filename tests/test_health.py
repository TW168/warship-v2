"""
tests/test_health.py — Test health endpoint functionality.

Basic smoke test to ensure the health endpoint returns the expected structure
and that the application starts correctly.
"""

import sys
from pathlib import Path

# Add the project root directory to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from fastapi.testclient import TestClient

from main import app

# Create test client
client = TestClient(app)


def test_health_endpoint():
    """Test that the health endpoint returns expected structure."""
    response = client.get("/health")
    
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "version" in data
    
    assert data["status"] == "ok"
    assert data["service"] == "warship"
    assert data["version"] == "0.1.0"


def test_health_endpoint_content_type():
    """Test that the health endpoint returns JSON content type."""
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


def test_root_endpoint_exists():
    """Test that the root endpoint exists and returns an HTML response."""
    response = client.get("/")
    
    # Should return 200 or potentially redirect, but not 404
    assert response.status_code in [200, 302, 307]