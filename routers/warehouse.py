"""
routers/warehouse.py — Warehouse management page routes.

Handles:
  GET /warehouse                          — Warehouse dashboard page
  GET /api/warehouse/udc-hourly           — UDC hourly missions from udc_hourly_ash table
  GET /api/warehouse/udc-summary          — UDC daily summary from udc_ash table
  GET /api/warehouse/ash-summary          — ASH event summary from event_ash table
  GET /api/warehouse/ash-descriptions     — Distinct ASH event descriptions from event_ash table
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database

router = APIRouter(tags=["Warehouse"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()


@router.get(
    "/warehouse",
    response_class=HTMLResponse,
    summary="Warehouse page",
    description="Warehouse operations dashboard: UDC hourly activity, UDC history trend, and ASH event heatmap.",
)
async def warehouse(request: Request) -> HTMLResponse:
    """Render the warehouse dashboard page."""
    return templates.TemplateResponse(
        "warehouse/index.html",
        {"request": request, "active_page": "warehouse"},
    )


@router.get(
    "/api/warehouse/udc-hourly",
    summary="UDC hourly missions",
    description=(
        "Returns all UDC mission records (Entry, Exit, Entry-1, Entry-5) with "
        "status 'Done' from the udc_hourly_ash table, ordered by dt_start."
    ),
)
async def udc_hourly() -> JSONResponse:
    """Fetch UDC hourly mission records from the warship database."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT *
                FROM udc_hourly_ash
                WHERE mission IN ('Entry', 'Exit', 'Entry-1', 'Entry-5')
                  AND status = 'Done'
                ORDER BY dt_start ASC
            """)).fetchall()

            result = []
            for row in rows:
                row_dict = dict(row._mapping)
                # Convert datetime objects to ISO strings for JSON serialization
                for key, val in row_dict.items():
                    if hasattr(val, "isoformat"):
                        row_dict[key] = val.isoformat()
                result.append(row_dict)

            return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/api/warehouse/udc-summary",
    summary="UDC summary by date range",
    description=(
        "Returns daily Entry/Exit/Entry-1/Entry-5 counts from the udc_ash table "
        "grouped by date. Used for the UDC history line chart."
    ),
)
async def udc_summary(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> JSONResponse:
    """Fetch UDC daily summary for a date range from the warship database."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    DATE(dt_end) AS `date`,
                    SUM(CASE WHEN mission = 'Entry'   THEN 1 ELSE 0 END) AS `Entry`,
                    SUM(CASE WHEN mission = 'Entry-1' THEN 1 ELSE 0 END) AS `Entry-1`,
                    SUM(CASE WHEN mission = 'Entry-5' THEN 1 ELSE 0 END) AS `Entry-5`,
                    SUM(CASE WHEN mission = 'Exit'    THEN 1 ELSE 0 END) AS `Exit`
                FROM udc_ash
                WHERE dt_end >= :start
                  AND dt_end <= :end
                GROUP BY DATE(dt_end)
                ORDER BY `date`
            """), {"start": start, "end": end}).fetchall()

            result = []
            for row in rows:
                row_dict = dict(row._mapping)
                for key, val in row_dict.items():
                    if hasattr(val, "isoformat"):
                        row_dict[key] = val.isoformat()
                    elif isinstance(val, int):
                        pass  # keep as int
                    else:
                        try:
                            row_dict[key] = int(val)
                        except (TypeError, ValueError):
                            pass
                result.append(row_dict)

            return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/api/warehouse/ash-summary",
    summary="ASH event summary by date range",
    description=(
        "Returns event_date, description, and total_count from the event_ash table "
        "grouped by event_date and description. Used for the ASH heatmap."
    ),
)
async def ash_summary(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
) -> JSONResponse:
    """Fetch ASH event summary for a date range from the warship database."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT event_date, description, COUNT(*) AS total_count
                FROM event_ash
                WHERE event_date BETWEEN :start_date AND :end_date
                GROUP BY event_date, description
                ORDER BY event_date ASC
            """), {"start_date": start_date, "end_date": end_date}).fetchall()

            result = []
            for row in rows:
                row_dict = dict(row._mapping)
                for key, val in row_dict.items():
                    if hasattr(val, "isoformat"):
                        row_dict[key] = val.isoformat()
                result.append(row_dict)

            return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/api/warehouse/ash-descriptions",
    summary="ASH event description catalog",
    description=(
        "Returns distinct ASH event descriptions from the last 365 days "
        "of the event_ash table."
    ),
)
async def ash_descriptions() -> JSONResponse:
    """Fetch the complete ASH event description catalog from the warship database."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT description
                FROM event_ash
                WHERE event_date >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
                ORDER BY description
            """)).fetchall()

            descriptions = [row.description for row in rows if row.description]
            return JSONResponse(content={"descriptions": descriptions})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
