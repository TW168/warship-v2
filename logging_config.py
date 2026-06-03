"""
logging_config.py — Centralized logging configuration for Warship application.

Provides structured logging with consistent formatting across all modules.
Configures both console and file logging with appropriate levels.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Configure application-wide logging with consistent formatting.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path. If None, logs to logs/warship.log
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        
    Returns:
        Configured root logger
    """
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Default log file path
    if log_file is None:
        log_file = log_dir / "warship.log"
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers to avoid duplication
    root_logger.handlers.clear()
    
    # Create formatter with timestamp, level, module, and message
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler for stdout/stderr
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Rotating file handler for persistent logging
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Prevent WatchFiles INFO events from creating a reload/log feedback loop.
    # With project-wide reload enabled, writing "1 change detected" into the
    # log file can itself become a watched change and trigger repeated events.
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.
    
    Args:
        name: Module name (usually __name__)
        
    Returns:
        Logger instance for the module
    """
    return logging.getLogger(name)


# Pre-configured loggers for common use cases
def get_router_logger(router_name: str) -> logging.Logger:
    """Get a logger for FastAPI routers."""
    return get_logger(f"warship.routers.{router_name}")


def get_util_logger(util_name: str) -> logging.Logger:
    """Get a logger for utility modules."""
    return get_logger(f"warship.utils.{util_name}")


def get_db_logger() -> logging.Logger:
    """Get a logger for database operations."""
    return get_logger("warship.database")