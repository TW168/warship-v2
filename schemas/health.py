"""
schemas/health.py — Pydantic response model for the health endpoint.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response schema for GET /health."""

    status: str         # "ok" or "error"
    service: str        # Service name
    version: str        # Semantic version string
    db: str             # "ok" or error message
