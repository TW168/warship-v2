"""
tests/test_logging_config.py — Test logging configuration functionality.

Tests the centralized logging infrastructure to ensure proper setup
and logger creation for different modules.
"""

import sys
from pathlib import Path

# Add the project root directory to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from logging_config import (
    setup_logging,
    get_logger,
    get_router_logger,
    get_util_logger,
    get_db_logger
)


def test_setup_logging_creates_logs_directory():
    """Test that setup_logging creates the logs directory."""
    with patch('logging_config.Path.mkdir') as mock_mkdir:
        setup_logging()
        
        # Verify logs directory creation was attempted
        mock_mkdir.assert_called_once_with(exist_ok=True)


def test_setup_logging_configures_root_logger():
    """Test that setup_logging properly configures the root logger."""
    with patch('logging_config.logging.getLogger') as mock_get_logger, \
         patch('logging_config.Path.mkdir'):
        
        mock_logger = mock_get_logger.return_value
        
        setup_logging(level="DEBUG")
        
        # Verify root logger configuration
        mock_get_logger.assert_called_with()
        mock_logger.setLevel.assert_called_with(logging.DEBUG)
        mock_logger.handlers.clear.assert_called_once()


def test_get_logger():
    """Test that get_logger returns a logger instance."""
    logger = get_logger("test_module")
    
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_module"


def test_get_router_logger():
    """Test that get_router_logger returns a properly named logger."""
    logger = get_router_logger("shipping")
    
    assert isinstance(logger, logging.Logger)
    assert logger.name == "warship.routers.shipping"


def test_get_util_logger():
    """Test that get_util_logger returns a properly named logger."""
    logger = get_util_logger("pdf_parser")
    
    assert isinstance(logger, logging.Logger)
    assert logger.name == "warship.utils.pdf_parser"


def test_get_db_logger():
    """Test that get_db_logger returns a properly named logger."""
    logger = get_db_logger()
    
    assert isinstance(logger, logging.Logger)
    assert logger.name == "warship.database"


def test_setup_logging_different_levels():
    """Test that setup_logging handles different log levels."""
    test_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    
    for level in test_levels:
        with patch('logging_config.logging.getLogger') as mock_get_logger, \
             patch('logging_config.Path.mkdir'):
            
            mock_logger = mock_get_logger.return_value
            
            setup_logging(level=level)
            
            expected_level = getattr(logging, level)
            mock_logger.setLevel.assert_called_with(expected_level)


def test_setup_logging_file_handler_configuration():
    """Test that file handler is configured with rotating logs."""
    with patch('logging_config.logging.handlers.RotatingFileHandler') as mock_handler, \
         patch('logging_config.logging.getLogger'), \
         patch('logging_config.Path.mkdir'):
        
        setup_logging(log_file="test.log", max_bytes=1000, backup_count=3)
        
        # Verify RotatingFileHandler configuration
        mock_handler.assert_called_once_with(
            filename="test.log",
            maxBytes=1000,
            backupCount=3,
            encoding='utf-8'
        )