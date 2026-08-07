"""
routers/warehouse.py — Warehouse management page routes.

Handles:
  GET /warehouse                          — Warehouse dashboard page
  GET /api/warehouse/udc-hourly           — UDC hourly missions from udc_hourly_ash table
  GET /api/warehouse/udc-summary          — UDC daily summary from udc_ash table
  GET /api/warehouse/ash-summary          — ASH event summary from event_ash table
  GET /api/warehouse/ash-descriptions     — Distinct ASH event descriptions from event_ash table
  GET /api/warehouse/pallet-entry-exit    — Pallet entry/exit totals from daily_shift_averages
  GET /warehouse/product-forecast         — Product Forecast Dashboard page
  GET /api/warehouse/product-forecast     — Product forecast JSON data
"""

from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger
from utils.product_forecast import compute_forecast

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - fallback for minimal environments
    BeautifulSoup = None

router = APIRouter(tags=["Warehouse"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()
logger = get_router_logger("warehouse")


def extract_prefix_pallets(html_text: str, prefix: str = "910") -> list[dict[str, str]]:
    """Extract pallet IDs from CFP rows that begin with the requested prefix."""
    if not html_text:
        return []

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")
        table = soup.find("table")
        if table is None:
            return []

        rows = table.find_all("tr")
        if not rows:
            return []

        header_cells = [cell.get_text(" ", strip=True).lower() for cell in rows[0].find_all(["th", "td"])]
        if "pallet 1" in header_cells and "pallet 2" in header_cells:
            pallet1_idx = header_cells.index("pallet 1")
            pallet2_idx = header_cells.index("pallet 2")
        else:
            pallet1_idx = 5
            pallet2_idx = 6

        matches: list[dict[str, str]] = []
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) <= max(pallet1_idx, pallet2_idx):
                continue

            for idx, location in ((pallet1_idx, "pallet_1"), (pallet2_idx, "pallet_2")):
                value = cells[idx].strip()
                if value and value.startswith(prefix):
                    matches.append({"pallet": value, "location": location})

        return matches

    return []


def count_prefix_pallets(html_text: str, prefix: str = "910") -> int:
    """Count pallet values in CFP HTML that begin with the requested prefix."""
    return len(extract_prefix_pallets(html_text, prefix=prefix))


@router.get(
    "/warehouse",
    response_class=HTMLResponse,
    summary="Warehouse page",
    description="Warehouse operations dashboard: UDC hourly activity, UDC history trend, ASH event heatmap, and CFP cell pallet counts.",
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
                        except (TypeError, ValueError) as e:
                            logger.debug(f"Could not convert value '{val}' to int for key '{key}': {e}")
                            # Keep original value if conversion fails
                            row_dict[key] = val
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


# ---------------------------------------------------------------------------
# Pallet entry/exit (daily_shift_averages)
# ---------------------------------------------------------------------------

_PALLET_ENTRY_EXIT_SQL = text("""
    SELECT
        SUM(avg_day_shift_in) + SUM(avg_night_shift_in) AS entry_to_date,
        SUM(avg_1st_shift_out)
          + SUM(avg_2nd_shift_out)
          + SUM(avg_3rd_shift_out) AS exit_to_date
    FROM warship.daily_shift_averages
    WHERE date BETWEEN :date_from AND :date_to
""")


@router.get(
    "/api/warehouse/pallet-entry-exit",
    summary="Pallet entry and exit totals",
    description=(
        "Returns pallet entry (day+night shift in) and exit (1st+2nd+3rd shift out) "
        "totals from daily_shift_averages for a given date range."
    ),
)
async def pallet_entry_exit(
    date_from: str = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: str = Query(..., description="End date (YYYY-MM-DD)"),
) -> JSONResponse:
    """Query daily_shift_averages for pallet entry/exit between two dates."""
    try:
        with _engine.connect() as conn:
            row = conn.execute(
                _PALLET_ENTRY_EXIT_SQL,
                {"date_from": date_from, "date_to": date_to},
            ).fetchone()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    entry = float(row.entry_to_date) if row and row.entry_to_date else 0
    exit_ = float(row.exit_to_date) if row and row.exit_to_date else 0

    return JSONResponse(content={
        "entry_to_date": round(entry),
        "exit_to_date": round(exit_),
        "date_from": date_from,
        "date_to": date_to,
    })


@router.get(
    "/api/warehouse/cfp-prefix-pallet-count",
    summary="CFP cell pallet count by prefix",
    description="Fetches the CFP cells page, counts pallet values that begin with the requested prefix, and returns the total.",
)
async def cfp_prefix_pallet_count(
    prefix: str = Query(default="910", description="Pallet prefix to count, e.g. 910"),
) -> JSONResponse:
    """Count pallet values in the CFP cells HTML that start with the requested prefix."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get("https://ash123.azurewebsites.net/cfpwh/cells/all_cells")
            response.raise_for_status()
            html_text = response.text
    except Exception as exc:
        logger.warning("Unable to fetch CFP cells data: %s", exc)
        return JSONResponse(status_code=502, content={"error": str(exc), "count": 0})

    matches = extract_prefix_pallets(html_text, prefix=prefix)
    return JSONResponse(content={"prefix": prefix, "count": len(matches), "items": matches})


# ---------------------------------------------------------------------------
# Product Forecast Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/warehouse/product-forecast",
    response_class=HTMLResponse,
    summary="Product Forecast Dashboard",
    description="Interactive dashboard showing per-product trend direction, momentum, and linear regression forecast.",
)
async def product_forecast_page(request: Request) -> HTMLResponse:
    """Render the Product Forecast Dashboard page."""
    return templates.TemplateResponse(
        "warehouse/product_forecast.html",
        {"request": request, "active_page": "product_forecast"},
    )


@router.get(
    "/api/warehouse/product-forecast",
    summary="Product forecast data",
    description=(
        "Computes per-product trend direction (INCREASE/DECREASE/STABLE), momentum, "
        "linear regression forecast, and R-squared from sp_get_all_shipped_product. "
        "Returns months array, per-product time series, forecast metrics, and summary counts."
    ),
)
async def product_forecast(
    site: str = Query(default="AMJK", description="Site code"),
    product_group: str = Query(default="SW", description="Product group"),
    start_date: str = Query(default="2010-01-01", description="Start date YYYY-MM-DD"),
    end_date: str = Query(default=None, description="End date YYYY-MM-DD (defaults to last day of previous month)"),
    min_months: int = Query(default=6, ge=1, description="Minimum active months to include a product"),
) -> JSONResponse:
    """Compute product forecast from shipped product stored procedure."""
    try:
        if end_date:
            resolved_end = end_date
        else:
            today = date.today()
            resolved_end = str(today.replace(day=1) - timedelta(days=1))
        result = compute_forecast(site, product_group, start_date, resolved_end, min_months)
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
