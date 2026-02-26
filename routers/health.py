"""
routers/health.py — Health check endpoint.
"""

from fastapi import APIRouter
from schemas.health import HealthResponse

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the current health status, service name, and version of the Warship application.",
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(status="ok", service="warship", version="0.1.0")
