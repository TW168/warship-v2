"""
routers/maintenance/freight_audit.py — Freight ¢/lb audit and validation routes.

Cross-validates freight cost-per-pound calculations across three independent
methods to ensure the Meeting Report, Carrier Cost SP, and Briefing page all
agree.  Designed to catch formula drift and data-quality issues early.

Audit methods
-------------
Method A — Weighted average of the ``Unit_Freight`` rate column:
    SUM(Unit_Freight × Pick_Weight) / SUM(Pick_Weight)
    Source: ``ipg_ez`` with NOT EXISTS deduplication (matches SP logic).

Method B — All-in cost from the ``Freight_Amount`` column:
    SUM(Freight_Amount) / SUM(Pick_Weight) × 100
    Source: actual dollar amounts invoiced on each BL.

Method C — Stored procedure ``sp_carrier_cost_per_pound``:
    Per-carrier ¢/lb weighted by carrier tonnage.

A sample of 15 random BLs is also returned so analysts can spot-verify
individual rows.

Routes:
    GET /frt-validation  — Freight ¢/lb by Product Code validation page
    GET /freight-audit   — Multi-method audit page (Jinja2 template)
    GET /api/freight-audit — JSON audit data for all three methods
"""

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# One shared engine for this module (created at import time)
_engine = connect_to_database()
logger = get_router_logger("maintenance.freight_audit")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@router.get(
    "/frt-validation",
    response_class=HTMLResponse,
    summary="Freight ¢/lb by Product Code Validation",
    description=(
        "Interactive tool to step-through the Freight ¢/lb by Product Code "
        "chart calculation: raw API data → per-product median → top-50 weight "
        "filter → BL number lookup."
    ),
)
async def frt_validation(request: Request) -> HTMLResponse:
    """Render the freight ¢/lb validation step-through tool."""
    return templates.TemplateResponse(
        "maintenance/frt_validation.html",
        {"request": request, "active_page": "frt_validation"},
    )


@router.get(
    "/freight-audit",
    response_class=HTMLResponse,
    summary="Freight ¢/lb Calculation Audit",
    description=(
        "Audit page that cross-checks freight cost-per-pound calculations across "
        "all pages (Meeting Report, Carrier Cost SP, Briefing) using three "
        "independent formulas and returns the raw intermediate values."
    ),
)
async def freight_audit(request: Request) -> HTMLResponse:
    """Render the freight calculation multi-method audit page."""
    return templates.TemplateResponse(
        "maintenance/freight_audit.html",
        {"request": request, "active_page": "freight_audit"},
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@router.get(
    "/api/freight-audit",
    summary="Freight ¢/lb Audit Data",
    description=(
        "Runs three independent queries against ``ipg_ez`` and "
        "``sp_carrier_cost_per_pound`` to cross-verify freight cost-per-pound "
        "calculations. Returns intermediate values for each formula step. "
        "Optional filters: ``site``, ``product_group``, ``date_from``, ``date_to``."
    ),
)
async def freight_audit_api(
    site:          Optional[str] = Query(None, description="Site code, e.g. AMJK"),
    product_group: Optional[str] = Query(None, description="Product group, e.g. SW"),
    date_from:     Optional[str] = Query(None, description="Truck_Appointment_Date >= YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="Truck_Appointment_Date <= YYYY-MM-DD"),
) -> JSONResponse:
    """Run all three audit methods and return comparison data for the UI.

    Uses the same NOT EXISTS deduplication as ``sp_carrier_cost_per_pound``
    to ensure apples-to-apples comparison across all methods.
    """
    # ── Build dynamic WHERE clause (mirrors SP deduplication exactly) ────────
    conditions = [
        "s.Truck_Appointment_Date IS NOT NULL",
        "s.Product_Code NOT IN ('INSERT-C', 'INSERT-3')",
    ]
    params: dict = {}

    if site:
        conditions.append("s.Site = :site")
        params["site"] = site
    if product_group:
        conditions.append("s.Product_Group = :product_group")
        params["product_group"] = product_group
    if date_from:
        conditions.append("s.Truck_Appointment_Date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("s.Truck_Appointment_Date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions)

    # NOT EXISTS dedup: keeps only the latest snapshot per BL number
    dedup = """
        AND NOT EXISTS (
            SELECT 1 FROM ipg_ez n
            WHERE n.BL_Number = s.BL_Number
              AND (n.snap_ts > s.snap_ts
                   OR (n.snap_ts = s.snap_ts AND n.file_name > s.file_name))
        )
    """

    try:
        with _engine.connect() as conn:

            # ── Method A & B: direct SQL aggregation ─────────────────────────
            row_a = conn.execute(
                text(
                    f"""
                    SELECT
                        SUM(s.Unit_Freight * s.Pick_Weight) AS uf_x_pw,
                        SUM(s.Pick_Weight)                  AS total_weight,
                        SUM(s.Freight_Amount)               AS total_freight_amt,
                        COUNT(*)                            AS row_count,
                        COUNT(DISTINCT s.BL_Number)         AS bl_count
                    FROM ipg_ez s
                    WHERE {where}
                    {dedup}
                    """
                ),
                params,
            ).fetchone()

            uf_x_pw       = float(row_a.uf_x_pw or 0)
            total_weight  = float(row_a.total_weight or 0)
            total_frt_amt = float(row_a.total_freight_amt or 0)
            row_count     = int(row_a.row_count or 0)
            bl_count      = int(row_a.bl_count or 0)

            # Method A: weighted-average rate (¢/lb)
            method_a = round(uf_x_pw / total_weight, 4) if total_weight else 0
            # Method B: all-in cost (¢/lb) — Freight_Amount is in dollars, ×100 for cents
            method_b = round((total_frt_amt / total_weight) * 100, 4) if total_weight else 0

            # ── Method C: stored procedure ───────────────────────────────────
            raw_conn = conn.connection.driver_connection
            cursor = raw_conn.cursor(dictionary=True)
            cursor.callproc(
                "sp_carrier_cost_per_pound",
                [date_from, date_to, site or None, product_group or None],
            )
            sp_rows: list[dict] = []
            sp_wtd_sum  = 0.0
            sp_total_wt = 0
            sp_total_frt = 0.0
            for result_set in cursor.stored_results():
                for r in result_set.fetchall():
                    cpp = float(r["cost_per_pound"]) if r["cost_per_pound"] else 0
                    wt  = int(r["total_weight"])      if r["total_weight"]   else 0
                    frt = float(r["total_freight_cost"] or 0)
                    sp_rows.append(
                        {
                            "carrier_id":         r["Carrier_ID"],
                            "total_weight":       wt,
                            "total_freight_cost": frt,
                            "cost_per_pound":     cpp,
                        }
                    )
                    sp_wtd_sum  += cpp * wt
                    sp_total_wt += wt
                    sp_total_frt += frt
            cursor.close()

            method_c = round(sp_wtd_sum / sp_total_wt, 4) if sp_total_wt else 0

            # ── Random BL sample for spot-verification ───────────────────────
            samples = conn.execute(
                text(
                    f"""
                    SELECT
                        s.BL_Number,
                        s.Unit_Freight,
                        s.Pick_Weight,
                        s.Freight_Amount,
                        ROUND(s.Unit_Freight / 100.0 * s.Pick_Weight, 2) AS computed_freight
                    FROM ipg_ez s
                    WHERE {where}
                      {dedup}
                      AND s.Unit_Freight   > 0
                      AND s.Pick_Weight    > 0
                      AND s.Freight_Amount > 0
                    ORDER BY RAND()
                    LIMIT 15
                    """
                ),
                params,
            ).fetchall()

            sample_rows = []
            for s in samples:
                uf       = float(s.Unit_Freight)
                pw       = float(s.Pick_Weight)
                fa       = float(s.Freight_Amount)
                computed = round(uf / 100.0 * pw, 2)
                sample_rows.append(
                    {
                        "bl":               s.BL_Number,
                        "unit_freight":     round(uf, 4),
                        "pick_weight":      round(pw, 0),
                        "freight_amount":   round(fa, 2),
                        "computed_freight": computed,
                        "diff":             round(fa - computed, 2),
                    }
                )

    except Exception as exc:
        logger.error(f"Freight audit calculation failed: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(
        content={
            "filters": {
                "site": site, "product_group": product_group,
                "date_from": date_from, "date_to": date_to,
            },
            "summary": {
                "row_count":         row_count,
                "bl_count":          bl_count,
                "total_weight":      round(total_weight, 0),
                "total_freight_amt": round(total_frt_amt, 2),
                "uf_x_pw":           round(uf_x_pw, 2),
            },
            "methods": {
                "a": {
                    "label":       "SUM(Unit_Freight × Pick_Weight) / SUM(Pick_Weight)",
                    "description": "Weighted avg of the per-pound RATE from the Excel report",
                    "unit":        "¢/lb",
                    "value":       method_a,
                    "source":      "Direct SQL on ipg_ez with dedup",
                },
                "b": {
                    "label":       "SUM(Freight_Amount) / SUM(Pick_Weight) × 100",
                    "description": "All-in cost per pound using actual BL dollar amounts (includes surcharges, fuel, etc.)",
                    "unit":        "¢/lb",
                    "value":       method_b,
                    "source":      "Freight_Amount column ($ on BL)",
                },
                "c": {
                    "label":       "SP sp_carrier_cost_per_pound → weighted avg",
                    "description": "Stored procedure per-carrier ¢/lb, then weighted by carrier weight",
                    "unit":        "¢/lb",
                    "value":       method_c,
                    "source":      "Stored procedure (uses Unit_Freight + dedup)",
                },
            },
            "sp_summary": {
                "total_weight":  sp_total_wt,
                "total_freight": round(sp_total_frt, 2),
            },
            "sp_carriers": sp_rows[:10],
            "samples":     sample_rows,
        }
    )
