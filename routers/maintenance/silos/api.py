"""
routers/maintenance/silos/api.py — Silos inventory and consumption-rate API endpoints.

These are the serving-layer endpoints that power the Silos Status dashboard.
Data is read from pre-computed aggregate tables (populated by the ETL pipeline)
so all queries are fast single-table scans — no joins at request time.

Routes:
    GET /api/silos/inventory-current   — Latest snapshot per vessel
    GET /api/silos/inventory-daily     — Daily aggregate trend (last N days)
    GET /api/silos/consumption-rate    — Per-product burn rate (last N days)
    GET /silos/consumption-rate        — Public root path for consumption-rate history
"""

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import connect_to_database
from utils.db_serializer import serialize_row

router = APIRouter(prefix="/api/silos", tags=["Silos"])
public_router = APIRouter(prefix="/silos", tags=["Silos"])

# One shared engine for this module (created at import time)
_engine = connect_to_database()


@router.get(
    "/inventory-current",
    summary="Silos Current Inventory",
    description=(
        "Returns the latest inventory reading per vessel from "
        "``silo_agg_inventory_current``, ordered by site then vessel name. "
        "Used to render the Current Inventory card row on the dashboard."
    ),
)
async def silos_inventory_current() -> JSONResponse:
    """Return per-vessel current inventory snapshot from the serving-layer aggregate."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    vessel_key, vessel_name, site, contents_code,
                    last_measurement_time, percent_full, product_weight,
                    product_height, alarm_code, severity_level, refreshed_at
                FROM silo_agg_inventory_current
                ORDER BY site, vessel_name
                """
            )
        ).mappings().all()

        # Fallback: if aggregate table is empty, serve today's latest per-vessel
        # rows directly from fact data so the dashboard remains usable.
        if not rows:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        f.vessel_key,
                        v.vessel_name,
                        v.site,
                        c.contents_code,
                        f.measurement_time AS last_measurement_time,
                        f.percent_full,
                        f.product_weight,
                        f.product_height,
                        a.alarm_code,
                        a.severity_level,
                        UTC_TIMESTAMP() AS refreshed_at
                    FROM fact_silo_status f
                    JOIN silo_dim_vessel v ON v.vessel_key = f.vessel_key
                    JOIN silo_dim_contents c ON c.contents_key = f.contents_key
                    JOIN silo_dim_alarm a ON a.alarm_key = f.alarm_key
                    JOIN (
                        SELECT vessel_key, MAX(measurement_time) AS max_measurement_time
                        FROM fact_silo_status
                        WHERE snapshot_date = CURDATE()
                        GROUP BY vessel_key
                    ) latest
                      ON latest.vessel_key = f.vessel_key
                     AND latest.max_measurement_time = f.measurement_time
                    WHERE f.snapshot_date = CURDATE()
                    ORDER BY v.site, v.vessel_name
                    """
                )
            ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.get(
    "/inventory-daily",
    summary="Silos Daily Inventory Trend",
    description=(
        "Returns daily aggregate inventory from ``silo_agg_inventory_daily`` "
        "for the last N days (default 30, max 365). "
        "Used to render the daily percentage-full trend chart."
        " Query params: ``days`` (int), ``contents_code`` (optional product filter)."
    ),
)
async def silos_inventory_daily(
    days: int = 30,
    contents_code: Optional[str] = Query(None, description="Filter to a single content code"),
) -> JSONResponse:
    """Return daily inventory trend for the requested lookback window."""
    days = max(1, min(days, 365))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    snapshot_date, contents_code, reading_count,
                    avg_percent_full, min_percent_full, max_percent_full,
                    total_product_weight, avg_product_weight
                FROM silo_agg_inventory_daily
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                  AND (:contents_code IS NULL OR contents_code = :contents_code)
                ORDER BY snapshot_date, contents_code
                """
            ),
            {"days": days, "contents_code": contents_code},
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.get(
    "/inventory-daily-actuals",
    summary="Silos Daily Actual Usage",
    description=(
        "Returns the total product weight by contents code for one exact snapshot "
        "date from the raw silo_status table. This is the actual usage side of the "
        "daily reconciliation view."
    ),
)
async def silos_inventory_daily_actuals(snapshot_date: str) -> JSONResponse:
    """Return exact-day product totals directly from the raw silo_status rows."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    contents AS contents_code,
                    SUM(COALESCE(product_weight, 0)) AS total_product_weight,
                    COUNT(*) AS reading_count
                FROM silo_status
                WHERE snapshot_date = :snapshot_date
                GROUP BY contents
                ORDER BY contents
                """
            ),
            {"snapshot_date": snapshot_date},
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.get(
    "/consumption-rate-daily",
    summary="Silos Daily Consumption Delta",
    description=(
        "Returns one-day per-product Consumption Rate delta values and derived "
        "consumed pounds (max(0, -delta)) from silo_agg_consumption_rate."
    ),
)
async def silos_consumption_rate_daily(snapshot_date: str) -> JSONResponse:
    """Return per-content daily delta and consumed pounds for one date."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    contents_code,
                    snapshot_date,
                    product_weight,
                    prev_day_weight,
                    weight_delta,
                    CASE
                        WHEN weight_delta < 0 THEN ABS(weight_delta)
                        ELSE 0
                    END AS consumed_lbs
                FROM silo_agg_consumption_rate
                WHERE snapshot_date = :snapshot_date
                ORDER BY contents_code
                """
            ),
            {"snapshot_date": snapshot_date},
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.get(
    "/consumption-rate",
    summary="Content Consumption / Burn Rate",
    description=(
        "Returns per-content daily consumption rate (weight delta summed across "
        "all vessels holding the same content) from ``silo_agg_consumption_rate`` "
        "for the last N days (default 30, max 365). "
        "Used to render the Consumption Rate burn-rate table. "
        "Query params: ``days`` (int), ``contents_code`` (optional content filter)."
    ),
)
@public_router.get(
    "/consumption-rate",
    summary="Content Consumption / Burn Rate",
    description=(
        "Returns per-content daily consumption rate (weight delta summed across "
        "all vessels holding the same content) from ``silo_agg_consumption_rate`` "
        "for the last N days (default 30, max 365). "
        "Public root path endpoint. "
        "Query params: ``days`` (int), ``contents_code`` (optional content filter)."
    ),
)
async def silos_consumption_rate(
    days: int = 30,
    contents_code: Optional[str] = Query(None, description="Filter to a single content code"),
) -> JSONResponse:
    """Return product burn-rate data (grain: contents_code × date) for the lookback window."""
    days = max(1, min(days, 365))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    contents_code, snapshot_date,
                    product_weight, prev_day_weight, weight_delta,
                    avg_7d_delta, days_to_empty
                FROM silo_agg_consumption_rate
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                  AND (:contents_code IS NULL OR contents_code = :contents_code)
                ORDER BY contents_code, snapshot_date
                """
            ),
            {"days": days, "contents_code": contents_code},
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})
