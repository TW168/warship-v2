"""
routers/maintenance/silos/anomaly_api.py — Anomaly event investigation API endpoints.

These endpoints expose the output of the ML anomaly detection pipeline for
operations teams to review, filter, and action suspicious consumption patterns.

Workflow
--------
1. Analyst opens the Silos dashboard and reviews anomaly events.
2. They filter by alert level (medium / high / critical) or status.
3. They update event status to 'acknowledged' or 'closed' with notes.

Routes:
    GET /api/silos/anomaly-features            — Historical risk-scored feature rows
    GET /api/silos/anomaly-events              — Investigation event queue
    PUT /api/silos/anomaly-events/{event_id}/status — Update workflow status
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import connect_to_database
from schemas.silos import SiloAnomalyStatusUpdateRequest
from utils.db_serializer import serialize_row

router = APIRouter(prefix="/api/silos", tags=["Silos"])

# One shared engine for this module (created at import time)
_engine = connect_to_database()


@router.get(
    "/anomaly-features",
    summary="Content Anomaly Feature History",
    description=(
        "Returns historical daily anomaly feature rows from "
        "``silo_ml_features_daily``, including rolling stats, z-scores, run "
        "lengths, and risk scores. "
        "Query params: ``days`` (lookback window, default 90), "
        "``min_risk`` (float 0–1, default 0.0), "
        "``contents_code`` (optional product filter)."
    ),
)
async def silos_anomaly_features(
    days: int = 90,
    min_risk: float = Query(0.0, ge=0.0, le=1.0, description="Minimum risk score (0–1)"),
    contents_code: Optional[str] = Query(None, description="Filter to a single product code"),
) -> JSONResponse:
    """Return the feature-engineered history used by the anomaly detection model.

    Useful for auditing why an event was (or was not) raised on a particular day.
    Results are ordered newest-first, then highest-risk-first.
    """
    days = max(1, min(days, 3650))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    snapshot_date, contents_code,
                    product_weight, prev_day_weight, weight_delta,
                    avg_delta_7, std_delta_7, avg_delta_30, std_delta_30,
                    zscore_30, days_to_empty, refill_flag, negative_run_len,
                    risk_score, alert_level, refreshed_at
                FROM silo_ml_features_daily
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                  AND risk_score   >= :min_risk
                  AND (:contents_code IS NULL OR contents_code = :contents_code)
                ORDER BY snapshot_date DESC, risk_score DESC, contents_code
                """
            ),
            {"days": days, "min_risk": min_risk, "contents_code": contents_code},
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.get(
    "/anomaly-events",
    summary="Content Anomaly Events",
    description=(
        "Returns the investigation event queue from ``silo_anomaly_events``. "
        "Query params: ``days`` (lookback, default 90), "
        "``status`` (open | acknowledged | closed), "
        "``min_level`` (medium | high | critical, default medium), "
        "``contents_code`` (optional content filter)."
    ),
)
async def silos_anomaly_events(
    days: int = 90,
    status: Optional[str] = Query(
        None,
        pattern="^(open|acknowledged|closed)$",
        description="Filter by workflow status",
    ),
    min_level: str = Query(
        "medium",
        pattern="^(medium|high|critical)$",
        description="Minimum alert level to return",
    ),
    contents_code: Optional[str] = Query(None, description="Filter to a single content code"),
) -> JSONResponse:
    """Return anomaly events for the operations investigation queue.

    Results include explanation text, analyst notes, and workflow status so
    the UI can render a full investigation timeline without extra queries.
    """
    days = max(1, min(days, 3650))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    id, snapshot_date, contents_code,
                    risk_score, alert_level, status,
                    weight_delta, zscore_30, days_to_empty, negative_run_len,
                    explanation, analyst_notes, created_at_utc, updated_at_utc
                FROM silo_anomaly_events
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                  AND (:status IS NULL OR status = :status)
                                    AND (:contents_code IS NULL OR contents_code = :contents_code)
                  AND (
                    CASE :min_level
                      WHEN 'critical' THEN alert_level = 'critical'
                      WHEN 'high'     THEN alert_level IN ('high', 'critical')
                      ELSE                 alert_level IN ('medium', 'high', 'critical')
                    END
                  )
                ORDER BY snapshot_date DESC, risk_score DESC, id DESC
                """
            ),
            {
                "days": days,
                "status": status,
                "min_level": min_level,
                "contents_code": contents_code,
            },
        ).mappings().all()

    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})


@router.put(
    "/anomaly-events/{event_id}/status",
    summary="Update Silo Anomaly Event Status",
    description=(
        "Updates the workflow status of one anomaly event. "
        "Valid status values: ``open``, ``acknowledged``, ``closed``. "
        "Optional ``notes`` field captures analyst findings."
    ),
)
async def silos_anomaly_event_update_status(
    event_id: int,
    body: SiloAnomalyStatusUpdateRequest,
) -> JSONResponse:
    """Update the investigation workflow status for a single anomaly event.

    Args:
        event_id: Primary key of the event to update.
        body:     New status and optional analyst notes.

    Returns:
        The full updated event row.

    Raises:
        HTTPException 400: Invalid status value.
        HTTPException 404: Event not found.
    """
    next_status = (body.status or "").strip().lower()
    if next_status not in {"open", "acknowledged", "closed"}:
        raise HTTPException(
            status_code=400,
            detail="status must be one of: open, acknowledged, closed",
        )

    with _engine.begin() as conn:
        updated = conn.execute(
            text(
                """
                UPDATE silo_anomaly_events
                SET
                    status         = :status,
                    analyst_notes  = :notes,
                    updated_at_utc = UTC_TIMESTAMP()
                WHERE id = :id
                """
            ),
            {"id": event_id, "status": next_status, "notes": body.notes},
        )

        if int(updated.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail="Anomaly event not found")

        row = conn.execute(
            text(
                """
                SELECT
                    id, snapshot_date, contents_code,
                    risk_score, alert_level, status,
                    weight_delta, zscore_30, days_to_empty, negative_run_len,
                    explanation, analyst_notes, created_at_utc, updated_at_utc
                FROM silo_anomaly_events
                WHERE id = :id
                """
            ),
            {"id": event_id},
        ).mappings().first()

    return JSONResponse(content={"data": serialize_row(row)})
