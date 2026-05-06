"""
tests/test_database.py — Test database connection functionality.

Tests the database connection factory and ensures it creates valid
SQLAlchemy engines with the expected configuration.
"""

import sys
from pathlib import Path

# Add the project root directory to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import patch
from sqlalchemy.engine import Engine

from database import connect_to_database


def test_connect_to_database_returns_engine():
    """Test that connect_to_database returns a SQLAlchemy Engine."""
    engine = connect_to_database()
    
    assert isinstance(engine, Engine)
    assert engine is not None


def test_connect_to_database_with_mysql():
    """Test that connect_to_database works with MySQL DBMS."""
    engine = connect_to_database(dbms="mysql")
    
    assert isinstance(engine, Engine)
    # Check that the connection string contains mysql
    connection_url = str(engine.url)
    assert "mysql+mysqlconnector" in connection_url


@patch('database.create_engine')
def test_connect_to_database_engine_configuration(mock_create_engine):
    """Test that the engine is configured with the correct parameters."""
    connect_to_database()
    
    # Verify create_engine was called with the expected parameters
    mock_create_engine.assert_called_once()
    
    # Get the call arguments
    args, kwargs = mock_create_engine.call_args
    
    # Check connection string format
    connection_string = args[0]
    assert "mysql+mysqlconnector://" in connection_string
    assert "@172.17.15.228:3306/warship" in connection_string
    
    # Check engine parameters
    assert kwargs.get('pool_pre_ping') is True
    assert kwargs.get('pool_recycle') == 1800


def test_connect_to_database_logging():
    """Test that database connection attempts are logged."""
    with patch('database.logger') as mock_logger:
        engine = connect_to_database()
        
        # Verify that info messages were logged
        mock_logger.info.assert_called()
        
        # Check that connection attempt was logged
        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("Connecting to" in call for call in log_calls)
        assert any("Database engine created successfully" in call for call in log_calls)