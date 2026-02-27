"""
routers/home.py — Home, Meeting Report, and Press page routes.

Includes:
  GET /                              — Home page (weather images)
  GET /meeting-report                — Meeting Report page (filter form)
  GET /api/meeting-report/results    — HTMX partial: query results as cards
  GET /press                         — Press sub-page
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database

router = APIRouter(tags=["Home"])
templates = Jinja2Templates(directory="templates")

# Create the DB engine once at module level (connection pool is reused per request)
_engine = connect_to_database()

# Meeting report SQL — groups customers into named locations, aggregates shipping metrics.
# Uses named parameters (:site, :product_group, :date) for safe parameterized execution.
_CARRIER_COUNT_SQL = text("""
    SELECT COUNT(*) AS carrier_count
    FROM (
        SELECT DISTINCT BL_Number, Carrier_ID, Truck_Appointment_Date
        FROM warship.vw_bl_lbs_cnt_carrier_customer
        WHERE site = :site
          AND product_group = :product_group
          AND Truck_Appointment_Date = :date
          AND Carrier_ID NOT IN ('SAIA-IP', 'CWF-IP')
    ) AS sub
""")

_MEETING_REPORT_SQL = text("""
    SELECT
        CASE
            WHEN Ship_to_Customer IN ('AMTOPP WAREHOUSE - HOUSTON')
                THEN 'Houston'
            WHEN Ship_to_Customer IN ('INTEPLAST GROUP CORP. (AMTOPP)')
                THEN 'Remington'
            WHEN Ship_to_Customer IN ('INTEPLAST GROUP CORP.(AMTOPP ( CFP)')
                THEN 'Phoenix'
            WHEN Ship_to_Customer IN ('PINNACLE FILMS')
                THEN 'Charlotte'
            ELSE 'Customers'
        END AS `Group`,

        SUM(pallet_count)                                       AS Pallets,
        SUM(pick_weight)                                        AS Weight,
        ROUND(SUM((Unit_Freight / 100.0) * Pick_Weight))        AS Freight,

        CASE
            WHEN SUM(pick_weight) > 0
                THEN ROUND(
                    SUM((Unit_Freight / 100.0) * Pick_Weight) / SUM(pick_weight),
                4)
            ELSE 0
        END AS Avg_Freight_per_lb

    FROM warship.vw_bl_lbs_cnt_carrier_customer
    WHERE site = :site
      AND product_group = :product_group
      AND Truck_Appointment_Date = :date
    GROUP BY
        CASE
            WHEN Ship_to_Customer IN ('AMTOPP WAREHOUSE - HOUSTON')
                THEN 'Houston'
            WHEN Ship_to_Customer IN ('INTEPLAST GROUP CORP. (AMTOPP)')
                THEN 'Remington'
            WHEN Ship_to_Customer IN ('INTEPLAST GROUP CORP.(AMTOPP ( CFP)')
                THEN 'Phoenix'
            WHEN Ship_to_Customer IN ('PINNACLE FILMS')
                THEN 'Charlotte'
            ELSE 'Customers'
        END
""")


@router.get(
    "/",
    response_class=HTMLResponse,
    summary="Home page",
    description="Main landing page displaying weather forecast images side by side.",
)
async def home(request: Request) -> HTMLResponse:
    """Render the home page."""
    return templates.TemplateResponse(
        "home/index.html",
        {"request": request, "active_page": "home"},
    )


@router.get(
    "/meeting-report",
    response_class=HTMLResponse,
    summary="Meeting Report page",
    description="Meeting reports and minutes sub-page under Home.",
)
async def meeting_report(request: Request) -> HTMLResponse:
    """Render the meeting report page with the filter form."""
    return templates.TemplateResponse(
        "home/meeting_report.html",
        {"request": request, "active_page": "meeting_report"},
    )


@router.get(
    "/api/meeting-report/results",
    response_class=HTMLResponse,
    summary="Meeting Report results",
    description=(
        "Executes the meeting report query filtered by site, product_group, and date. "
        "Returns an HTML partial (cards) consumed by HTMX on the Meeting Report page."
    ),
)
async def meeting_report_results(
    request: Request,
    site: str = Query(..., description="Site code, e.g. 'CFP'"),
    product_group: str = Query(..., description="Product group identifier"),
    date: str = Query(..., description="Truck appointment date (YYYY-MM-DD)"),
) -> HTMLResponse:
    """
    Run the aggregated meeting report query and return rendered result cards.
    On DB error, the partial displays an error alert instead of crashing the page.
    """
    rows = []
    carrier_count = 0
    error = None

    try:
        with _engine.connect() as conn:
            result = conn.execute(
                _MEETING_REPORT_SQL,
                {"site": site, "product_group": product_group, "date": date},
            )
            # Convert each row to a plain dict, casting Decimal → float so
            # Jinja2 arithmetic and Python number formatting work correctly.
            # MySQL SUM/ROUND returns decimal.Decimal which is not JSON/template-safe.
            numeric_keys = {"Pallets", "Weight", "Freight", "Avg_Freight_per_lb"}
            rows = [
                {
                    k: float(v) if k in numeric_keys and v is not None else v
                    for k, v in row._mapping.items()
                }
                for row in result.fetchall()
            ]

            carrier_result = conn.execute(
                _CARRIER_COUNT_SQL,
                {"site": site, "product_group": product_group, "date": date},
            )
            carrier_count = int(carrier_result.scalar() or 0)
    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(
        "home/meeting_report_results.html",
        {
            "request": request,
            "rows": rows,
            "carrier_count": carrier_count,
            "error": error,
            "site": site,
            "product_group": product_group,
            "date": date,
        },
    )


@router.get(
    "/press",
    response_class=HTMLResponse,
    summary="Press page",
    description="Press releases and news sub-page under Home.",
)
async def press(request: Request) -> HTMLResponse:
    """Render the press sub-page."""
    return templates.TemplateResponse(
        "home/press.html",
        {"request": request, "active_page": "press"},
    )
