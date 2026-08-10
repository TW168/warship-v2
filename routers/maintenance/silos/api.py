"""
routers/maintenance/silos/api.py — Silos inventory and consumption-rate API endpoints.

These are the serving-layer endpoints that power the Silos Status dashboard.
Data is read from pre-computed aggregate tables (populated by the ETL pipeline)
so all queries are fast single-table scans — no joins at request time.

Routes:
    GET /api/silos/inventory-current        — Latest snapshot per vessel
    GET /api/silos/inventory-daily          — Daily aggregate trend (last N days)
    GET /api/silos/resin-pallet-yield       — Rolling resin lbs consumed per pallet produced
    GET /api/silos/consumption-rate         — Per-product burn rate (last N days)
    GET /silos/consumption-rate             — Public root path for consumption-rate history
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


def _normalize_day(value: object) -> str | None:
    """Normalize a date-like value to YYYY-MM-DD for chart joins."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _build_resin_pallet_yield_series(
    daily_rows: list[dict],
    window: int,
    keep_days: Optional[int] = None,
) -> list[dict]:
    """Add a trailing-window resin-per-pallet yield to a daily consumption/production series.

    ``daily_rows`` must be ascending by date, each row carrying ``date``,
    ``resin_lbs`` (pounds drawn from the silos that day) and ``pallets_in``
    (pallets produced into the warehouse that day).

    The rolling yield is a **ratio of sums** over the trailing window
    (total resin / total pallets), not an average of the daily ratios. Daily
    ratios swing by more than 10x because silo readings are taken at varying
    times and a day's resin draw does not map to that same day's pallets;
    summing both sides across the window is what cancels that timing noise.

    ``keep_days`` trims the leading rows that only existed to seed the first
    window, so callers can request extra history without exposing it.
    """
    window = max(1, window)
    series: list[dict] = []

    for index, row in enumerate(daily_rows):
        day = _normalize_day(row.get("date"))
        if day is None:
            continue

        resin_lbs = float(row.get("resin_lbs") or 0.0)
        pallets_in = float(row.get("pallets_in") or 0.0)

        # Trailing window inclusive of the current day.
        window_start = max(0, index - window + 1)
        window_rows = daily_rows[window_start : index + 1]
        window_resin = sum(float(r.get("resin_lbs") or 0.0) for r in window_rows)
        window_pallets = sum(float(r.get("pallets_in") or 0.0) for r in window_rows)

        series.append(
            {
                "date": day,
                "resin_lbs": resin_lbs,
                "pallets_in": pallets_in,
                # Daily ratio is kept only as context - it is deliberately noisy.
                "daily_yield": (resin_lbs / pallets_in) if pallets_in > 0 else None,
                "rolling_resin_lbs": window_resin,
                "rolling_pallets_in": window_pallets,
                "rolling_yield": (window_resin / window_pallets) if window_pallets > 0 else None,
                # False while the trailing window is still filling up.
                "rolling_complete": len(window_rows) == window,
            }
        )

    if keep_days is not None and keep_days > 0:
        series = series[-keep_days:]
    return series


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
    "/resin-pallet-yield",
    summary="Rolling resin-per-pallet yield",
    description=(
        "Returns pounds of resin drawn from the silos per pallet produced into the "
        "warehouse, as a trailing-window rolling ratio. Resin consumption is derived "
        "from day-over-day decreases in end-of-day silo weight per vessel (increases "
        "are refills and are excluded), and pallet production comes from the "
        "deduplicated ``daily_shift_averages`` shift-in columns. "
        "Query params: ``days`` (lookback, default 30) and ``window`` (rolling window "
        "in days, default 7)."
    ),
)
async def silos_resin_pallet_yield(
    days: int = Query(30, ge=1, le=365, description="Days of history to return"),
    window: int = Query(7, ge=1, le=30, description="Trailing rolling-window size in days"),
) -> JSONResponse:
    """Return a daily and trailing-window resin-per-pallet yield series."""
    # Pull extra leading days so the first returned row already has a full window.
    lookback = days + window

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH eod AS (
                    -- Last reading of each day per vessel; snapshots land at varying times.
                    SELECT
                        snapshot_date,
                        vessel_name,
                        product_weight,
                        ROW_NUMBER() OVER (
                            PARTITION BY vessel_name, snapshot_date
                            ORDER BY measurement_time DESC
                        ) AS rn
                    FROM silo_status
                    WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :lookback DAY)
                ),
                day_end AS (
                    SELECT snapshot_date, vessel_name, product_weight
                    FROM eod
                    WHERE rn = 1
                ),
                lagged AS (
                    SELECT
                        snapshot_date,
                        vessel_name,
                        product_weight,
                        LAG(product_weight) OVER (
                            PARTITION BY vessel_name ORDER BY snapshot_date
                        ) AS prev_weight
                    FROM day_end
                ),
                consumed AS (
                    -- Only weight decreases count as consumption; increases are deliveries.
                    SELECT
                        snapshot_date,
                        SUM(GREATEST(0, prev_weight - product_weight)) AS resin_lbs
                    FROM lagged
                    WHERE prev_weight IS NOT NULL
                    GROUP BY snapshot_date
                )
                SELECT
                    c.snapshot_date AS date,
                    c.resin_lbs,
                    (
                        COALESCE(a.avg_day_shift_in, 0)
                        + COALESCE(a.avg_night_shift_in, 0)
                    ) AS pallets_in
                FROM consumed c
                JOIN daily_shift_averages a
                  ON a.`Date` = DATE_FORMAT(c.snapshot_date, '%Y-%m-%d')
                ORDER BY c.snapshot_date
                """
            ),
            {"lookback": lookback},
        ).mappings().all()

    daily_rows = [
        {
            "date": row["date"],
            "resin_lbs": float(row["resin_lbs"] or 0),
            "pallets_in": float(row["pallets_in"] or 0),
        }
        for row in rows
    ]
    series = _build_resin_pallet_yield_series(daily_rows, window=window, keep_days=days)
    return JSONResponse(content={"window": window, "data": series})


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
