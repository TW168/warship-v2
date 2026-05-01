"""
routers/maintenance/silos/anomaly.py — Anomaly feature engineering and event generation.

Provides two ETL functions called by the upload pipeline after each CSV ingest:

    _ensure_silo_anomaly_tables(engine)
        DDL-safe creation of silo_ml_features_daily and silo_anomaly_events.

    _refresh_silo_anomaly_features(conn, snapshot_date) -> int
        Recomputes one day of ML feature rows using rolling window statistics,
        z-scores, run-length encoding, and a weighted risk-score formula.

    _refresh_silo_anomaly_events(conn, snapshot_date) -> int
        Promotes medium/high/critical feature rows into the investigation queue
        (silo_anomaly_events).

Both refresh functions receive an open SQLAlchemy connection/transaction so they
participate in the caller's transaction and never commit independently.

Risk score weighting
--------------------
Component                                   Max weight
----------------------------------------    ----------
z-score ≤ -3 (extreme negative deviation)   0.55
z-score ≤ -2 (significant deviation)        0.35
7-day spike (|delta - avg7| > 2 * std7)     0.20
Days-to-empty < 3                           0.20
Days-to-empty < 7                           0.10
Negative-run ≥ 5 consecutive days           0.15
Negative-run ≥ 3 consecutive days           0.08
Refill detected (weight UP)                 -0.25  (reduces false positives)

Final risk_score is clamped to [0.0, 1.0].

Alert levels
------------
≥ 0.80 → critical
≥ 0.65 → high
≥ 0.45 → medium
< 0.45 → low  (not promoted to events table)
"""

from datetime import date

from sqlalchemy import text


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def _ensure_silo_anomaly_tables(engine) -> None:
    """Create anomaly feature/event tables if they do not already exist.

    Safe to call on every startup or upload — uses CREATE TABLE IF NOT EXISTS.

    Args:
        engine: SQLAlchemy Engine connected to the warship database.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS silo_ml_features_daily (
                    snapshot_date   DATE         NOT NULL,
                    contents_code   VARCHAR(100) NOT NULL,
                    product_weight  DECIMAL(18,4) NULL,
                    prev_day_weight DECIMAL(18,4) NULL,
                    weight_delta    DECIMAL(18,4) NULL,
                    avg_delta_7     DECIMAL(18,4) NULL,
                    std_delta_7     DECIMAL(18,4) NULL,
                    avg_delta_30    DECIMAL(18,4) NULL,
                    std_delta_30    DECIMAL(18,4) NULL,
                    zscore_30       DECIMAL(18,4) NULL,
                    days_to_empty   DECIMAL(10,2) NULL,
                    refill_flag     TINYINT(1)   NOT NULL DEFAULT 0,
                    negative_run_len INT          NOT NULL DEFAULT 0,
                    risk_score      DECIMAL(5,4) NOT NULL DEFAULT 0,
                    alert_level     VARCHAR(16)  NOT NULL DEFAULT 'low',
                    refreshed_at    DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    PRIMARY KEY (contents_code, snapshot_date),
                    KEY ix_silo_ml_features_daily_snapshot_date (snapshot_date),
                    KEY ix_silo_ml_features_daily_alert_level   (alert_level),
                    KEY ix_silo_ml_features_daily_risk_score    (risk_score)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS silo_anomaly_events (
                    id               BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    snapshot_date    DATE         NOT NULL,
                    contents_code    VARCHAR(100) NOT NULL,
                    risk_score       DECIMAL(5,4) NOT NULL,
                    alert_level      VARCHAR(16)  NOT NULL,
                    weight_delta     DECIMAL(18,4) NULL,
                    zscore_30        DECIMAL(18,4) NULL,
                    days_to_empty    DECIMAL(10,2) NULL,
                    negative_run_len INT          NOT NULL DEFAULT 0,
                    explanation      TEXT         NULL,
                    status           VARCHAR(16)  NOT NULL DEFAULT 'open',
                    analyst_notes    TEXT         NULL,
                    created_at_utc   DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    updated_at_utc   DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    UNIQUE KEY uq_silo_anomaly_event_day_content (snapshot_date, contents_code),
                    KEY ix_silo_anomaly_events_snapshot_date  (snapshot_date),
                    KEY ix_silo_anomaly_events_status         (status),
                    KEY ix_silo_anomaly_events_alert_level    (alert_level)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _refresh_silo_anomaly_features(conn, snapshot_date: date) -> int:
    """Recompute one day of anomaly feature rows for all product codes.

    Steps:
    1. Delete any existing rows for snapshot_date (idempotent re-run).
    2. Pull rolling window stats (7d, 30d avg/stddev) from silo_agg_consumption_rate.
    3. Compute z-score against the 30-day distribution.
    4. Compute negative-run-length (consecutive days of weight decline) via gap-and-island.
    5. Score each row with the weighted risk formula and clamp to [0, 1].
    6. Assign alert level and insert only the target day's results.

    Args:
        conn:          An open SQLAlchemy connection (part of a parent transaction).
        snapshot_date: The calendar date to compute features for.

    Returns:
        Number of feature rows inserted.
    """
    # Delete before re-insert so this function is safe to call multiple times
    conn.execute(
        text("DELETE FROM silo_ml_features_daily WHERE snapshot_date = :sd"),
        {"sd": snapshot_date},
    )

    res = conn.execute(
        text(
            """
            INSERT INTO silo_ml_features_daily (
                snapshot_date, contents_code,
                product_weight, prev_day_weight, weight_delta,
                avg_delta_7, std_delta_7, avg_delta_30, std_delta_30,
                zscore_30, days_to_empty, refill_flag, negative_run_len,
                risk_score, alert_level, refreshed_at
            )
            /* ── Step 1: pull all history up to target day ─────────────────── */
            WITH base AS (
                SELECT
                    snapshot_date,
                    contents_code,
                    product_weight,
                    prev_day_weight,
                    weight_delta,
                    days_to_empty
                FROM silo_agg_consumption_rate
                WHERE snapshot_date <= :sd
            ),
            /* ── Step 2: rolling window statistics ──────────────────────────── */
            staged AS (
                SELECT
                    b.*,
                    AVG(b.weight_delta) OVER (
                        PARTITION BY b.contents_code
                        ORDER BY b.snapshot_date
                        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                    ) AS avg_delta_7,
                    STDDEV_SAMP(b.weight_delta) OVER (
                        PARTITION BY b.contents_code
                        ORDER BY b.snapshot_date
                        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                    ) AS std_delta_7,
                    AVG(b.weight_delta) OVER (
                        PARTITION BY b.contents_code
                        ORDER BY b.snapshot_date
                        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                    ) AS avg_delta_30,
                    STDDEV_SAMP(b.weight_delta) OVER (
                        PARTITION BY b.contents_code
                        ORDER BY b.snapshot_date
                        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                    ) AS std_delta_30,
                    CASE WHEN b.weight_delta > 0 THEN 1 ELSE 0 END AS refill_flag,
                    /* Gap-and-island: partition negative streaks by non-negative breaks */
                    SUM(CASE WHEN b.weight_delta < 0 THEN 0 ELSE 1 END) OVER (
                        PARTITION BY b.contents_code
                        ORDER BY b.snapshot_date
                    ) AS nonneg_group
                FROM base b
            ),
            /* ── Step 3: z-score + negative run-length ──────────────────────── */
            calc AS (
                SELECT
                    s.*,
                    CASE
                        WHEN s.weight_delta < 0
                        THEN ROW_NUMBER() OVER (
                                PARTITION BY s.contents_code, s.nonneg_group
                                ORDER BY s.snapshot_date
                             )
                        ELSE 0
                    END AS negative_run_len,
                    CASE
                        WHEN s.std_delta_30 IS NULL OR s.std_delta_30 = 0 THEN NULL
                        ELSE ROUND(
                            (s.weight_delta - s.avg_delta_30) / s.std_delta_30,
                            4
                        )
                    END AS zscore_30
                FROM staged s
            ),
            /* ── Step 4: weighted risk score (unclamped) ────────────────────── */
            scored AS (
                SELECT
                    c.*,
                    (
                        /* z-score component — extreme deviations signal theft / leak */
                        CASE
                            WHEN c.zscore_30 <= -3 THEN 0.55
                            WHEN c.zscore_30 <= -2 THEN 0.35
                            ELSE 0
                        END
                        /* short-term spike component */
                        + CASE
                            WHEN c.std_delta_7 IS NOT NULL
                             AND c.std_delta_7 > 0
                             AND ABS(c.weight_delta - c.avg_delta_7) > (2 * c.std_delta_7)
                            THEN 0.20
                            ELSE 0
                          END
                        /* days-to-empty urgency */
                        + CASE
                            WHEN c.days_to_empty IS NOT NULL AND c.days_to_empty < 3 THEN 0.20
                            WHEN c.days_to_empty IS NOT NULL AND c.days_to_empty < 7 THEN 0.10
                            ELSE 0
                          END
                        /* sustained negative run length */
                        + CASE
                            WHEN c.negative_run_len >= 5 THEN 0.15
                            WHEN c.negative_run_len >= 3 THEN 0.08
                            ELSE 0
                          END
                        /* refill detected — reduces false positives */
                        + CASE WHEN c.refill_flag = 1 THEN -0.25 ELSE 0 END
                    ) AS raw_risk_score
                FROM calc c
            ),
            /* ── Step 5: clamp risk to [0, 1] ───────────────────────────────── */
            bounded AS (
                SELECT
                    snapshot_date,
                    contents_code,
                    product_weight,
                    prev_day_weight,
                    weight_delta,
                    avg_delta_7,
                    std_delta_7,
                    avg_delta_30,
                    std_delta_30,
                    zscore_30,
                    days_to_empty,
                    refill_flag,
                    negative_run_len,
                    LEAST(GREATEST(raw_risk_score, 0), 1) AS risk_score
                FROM scored
            )
            /* ── Step 6: filter to target day only, assign alert level ──────── */
            SELECT
                snapshot_date,
                contents_code,
                product_weight,
                prev_day_weight,
                weight_delta,
                avg_delta_7,
                std_delta_7,
                avg_delta_30,
                std_delta_30,
                zscore_30,
                days_to_empty,
                refill_flag,
                negative_run_len,
                risk_score,
                CASE
                    WHEN risk_score >= 0.80 THEN 'critical'
                    WHEN risk_score >= 0.65 THEN 'high'
                    WHEN risk_score >= 0.45 THEN 'medium'
                    ELSE 'low'
                END AS alert_level,
                UTC_TIMESTAMP()
            FROM bounded
            WHERE snapshot_date = :sd
            """
        ),
        {"sd": snapshot_date},
    )
    return int(res.rowcount or 0)


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------

def _refresh_silo_anomaly_events(conn, snapshot_date: date) -> int:
    """Promote medium/high/critical feature rows into the investigation event queue.

    Deletes any existing events for snapshot_date and re-inserts from the
    freshly computed silo_ml_features_daily rows where alert_level != 'low'.

    The event's explanation field is a compact summary string that operations
    analysts can read at a glance without joining back to the features table.

    Args:
        conn:          An open SQLAlchemy connection (part of a parent transaction).
        snapshot_date: The calendar date to generate events for.

    Returns:
        Number of anomaly event rows inserted.
    """
    conn.execute(
        text("DELETE FROM silo_anomaly_events WHERE snapshot_date = :sd"),
        {"sd": snapshot_date},
    )

    res = conn.execute(
        text(
            """
            INSERT INTO silo_anomaly_events (
                snapshot_date, contents_code, risk_score, alert_level,
                weight_delta, zscore_30, days_to_empty, negative_run_len,
                explanation, status, created_at_utc, updated_at_utc
            )
            SELECT
                f.snapshot_date,
                f.contents_code,
                f.risk_score,
                f.alert_level,
                f.weight_delta,
                f.zscore_30,
                f.days_to_empty,
                f.negative_run_len,
                CONCAT(
                    'Anomaly score=', ROUND(f.risk_score, 2),
                    '; delta=',         ROUND(f.weight_delta, 2),
                    '; z30=',           COALESCE(ROUND(f.zscore_30, 2), 'null'),
                    '; days_to_empty=', COALESCE(ROUND(f.days_to_empty, 1), 'null'),
                    '; negative_run_len=', f.negative_run_len
                ) AS explanation,
                'open'         AS status,
                UTC_TIMESTAMP(),
                UTC_TIMESTAMP()
            FROM silo_ml_features_daily f
            WHERE f.snapshot_date = :sd
              AND f.alert_level IN ('critical', 'high', 'medium')
            """
        ),
        {"sd": snapshot_date},
    )
    return int(res.rowcount or 0)
