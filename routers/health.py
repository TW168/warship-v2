"""
routers/health.py — Health check endpoint.

Checks both app liveness and database connectivity.
Returns HTTP 200 when healthy, HTTP 503 when the DB is unreachable.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import connect_to_database
from schemas.health import HealthResponse

router = APIRouter(tags=["System"])

_engine = connect_to_database()


@router.get(
    "/health",
    summary="Health check",
    description=(
        "Returns HTTP 200 when the app and database are healthy. "
        "Returns HTTP 503 if the database is unreachable."
    ),
)
async def health_check() -> JSONResponse:
    """Ping the DB and return health status. 503 on failure so monitors detect it."""
    db_status = "ok"
    http_status = 200

    try:
        # connect_args timeout prevents hanging when MySQL is slow/unreachable
        with _engine.connect().execution_options(timeout=3) as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = str(exc)
        http_status = 503

    payload = HealthResponse(
        status="ok" if http_status == 200 else "error",
        service="warship",
        version="0.1.0",
        db=db_status,
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
