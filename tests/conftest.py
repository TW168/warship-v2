"""
tests/conftest.py — Pytest configuration and shared fixtures.

Provides shared test fixtures and configuration for the entire test suite.
"""

import sys
from pathlib import Path

# Add the project root directory to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client():
    """
    Create a test client for the FastAPI application.
    
    Uses session scope so the client is created once per test session
    and reused across all tests for better performance.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def setup_logging(caplog):
    """
    Configure logging for tests.
    
    This fixture runs automatically for all tests and ensures logging
    is properly configured and captured by pytest.
    """
    # Set log level to INFO to capture important messages during tests
    caplog.set_level("INFO")


# Mock database engine for tests that need database isolation
@pytest.fixture
def mock_engine():
    """
    Mock database engine for tests that need database isolation.
    
    Use this fixture when testing database-dependent functionality
    without requiring a real database connection.
    """
    from unittest.mock import Mock
    
    mock_engine = Mock()
    # Configure the mock as needed for specific tests
    yield mock_engine