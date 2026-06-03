"""Maintenance routes for SW Transport Type analysis (transp_type_john table).

Provides:
  GET  /maintenance/transp-type            — HTML dashboard page
  GET  /maintenance/api/transp-type-by-year — JSON annual breakdown
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()
logger = get_router_logger("transp_type")

# Transport types that make up "Prepaid Total" — used for stacked chart.
# Excludes CPU (Lolita) and Warehouse which are not part of the prepaid subtotal.
_PREPAID_TYPES = {"FTL", "LTL", "Export", "Intermodal", "Reconsignment", "Sample", "Railcar"}


@router.get(
    "/transp-type",
    response_class=HTMLResponse,
    name="transp_type_page",
    summary="SW Transport Type Analysis",
    description="Renders the annual SW shipment transport-type breakdown dashboard.",
)
async def transp_type_page(request: Request) -> HTMLResponse:
    """Render the transport type analysis dashboard page."""
    return templates.TemplateResponse(
        "maintenance/transp_type.html",
        {
            "request": request,
            "active_page": "transp_type",
        },
    )


@router.get(
    "/api/transp-type-by-year",
    response_class=JSONResponse,
    name="transp_type_by_year_api",
    summary="Transport type annual breakdown",
    description=(
        "Returns annual lbs by transport type from transp_type_john. "
        "'Prepaid Total' is returned as a separate reference series "
        "(it is a subtotal row — FTL + LTL + Export + Intermodal + "
        "Reconsignment + Sample) and is excluded from the stacked breakdown "
        "to prevent double-counting. Zero-weight type/year combinations "
        "are omitted from the type list."
    ),
)
async def transp_type_by_year_api(
    site: str = Query(default="SW", description="Site code (default SW)"),
) -> JSONResponse:
    """Query transp_type_john and return annual transport-type data."""
    logger.info("transp-type-by-year requested for site=%s", site)
    try:
        with _engine.connect() as conn:
            # Individual transport types (excludes Prepaid Total subtotal row)
            type_rows = conn.execute(
                text("""
                    SELECT yyyy, trans_type, SUM(wt_lbs) AS lbs
                    FROM transp_type_john
                    WHERE trans_type != 'Prepaid Total'
                      AND site = :site
                    GROUP BY yyyy, trans_type
                    ORDER BY yyyy, trans_type
                """),
                {"site": site},
            ).fetchall()

            # Prepaid Total subtotal per year
            total_rows = conn.execute(
                text("""
                    SELECT yyyy, SUM(wt_lbs) AS lbs
                    FROM transp_type_john
                    WHERE trans_type = 'Prepaid Total'
                      AND site = :site
                    GROUP BY yyyy
                    ORDER BY yyyy
                """),
                {"site": site},
            ).fetchall()

    except Exception:
        logger.exception("DB error in transp-type-by-year")
        return JSONResponse({"error": "Database error"}, status_code=500)

    # Build {year: {trans_type: lbs}} mapping
    year_type: dict[int, dict[str, int]] = defaultdict(dict)
    years_set: set[int] = set()
    types_seen: dict[str, int] = defaultdict(int)  # type → total lbs across all years

    for row in type_rows:
        yr = int(row[0])
        tt = str(row[1])
        lbs = int(row[2]) if row[2] else 0
        year_type[yr][tt] = lbs
        years_set.add(yr)
        types_seen[tt] += lbs

    years = sorted(years_set)

    # Only include types that have at least 1 lb across all years
    types = [tt for tt, total in sorted(types_seen.items(), key=lambda x: -x[1]) if total > 0]

    # Build per-type series for Plotly
    series = [
        {
            "name": tt,
            "data": [year_type[yr].get(tt, 0) for yr in years],
        }
        for tt in types
    ]

    # Prepaid Total reference line
    prepaid_by_year = {int(r[0]): int(r[1]) if r[1] else 0 for r in total_rows}
    prepaid_series = [prepaid_by_year.get(yr, 0) for yr in years]

    # KPI: latest full year (prior year to current partial)
    import datetime
    current_year = datetime.date.today().year
    full_years = [y for y in years if y < current_year]
    latest_full_yr = full_years[-1] if full_years else years[-1] if years else None

    kpi: dict = {}
    if latest_full_yr and latest_full_yr in year_type:
        yt = year_type[latest_full_yr]
        ftl = yt.get("FTL", 0)
        ltl = yt.get("LTL", 0)
        pt = prepaid_by_year.get(latest_full_yr, 0)
        other = pt - ftl - ltl if pt > 0 else sum(v for k, v in yt.items() if k not in {"FTL", "LTL"})
        total = pt if pt > 0 else sum(yt.values())
        kpi = {
            "year": latest_full_yr,
            "ftl_lbs": ftl,
            "ltl_lbs": ltl,
            "other_lbs": other,
            "prepaid_total_lbs": pt or total,
            "ftl_pct": round(ftl / total * 100, 1) if total else 0,
            "ltl_pct": round(ltl / total * 100, 1) if total else 0,
        }

    logger.info("transp-type-by-year returned %d years, %d types", len(years), len(types))
    return JSONResponse(
        {
            "years": years,
            "series": series,
            "prepaid_total": prepaid_series,
            "site": site,
            "kpi": kpi,
        }
    )
