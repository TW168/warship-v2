"""
routers/maintenance/silos/etl.py — Star-schema ETL pipeline for silo data.

Entry point: ``_run_silo_etl(snapshot_date)``

Called automatically after each successful CSV upload. Reads raw rows from
``silo_status`` for the given snapshot_date and populates the full star-schema:

    Dimension tables (upsert / insert-if-missing):
        silo_dim_vessel     — one row per physical silo vessel
        silo_dim_contents   — one row per product / material code
        silo_dim_alarm      — one row per alarm condition string

    Fact table:
        fact_silo_status    — one row per measurement reading

    Serving-layer aggregates (DELETE + INSERT for the target date):
        silo_agg_inventory_current   — latest per-vessel snapshot
        silo_agg_inventory_daily     — daily totals per product code
        silo_agg_consumption_rate    — day-over-day delta, days-to-empty
        silo_agg_alarm_stats         — alarm counts per vessel per day
        silo_agg_silo_utilization    — monthly utilisation stats

    Anomaly pipeline (delegated to anomaly.py):
        silo_ml_features_daily       — risk-scored features
        silo_anomaly_events          — investigation event queue

All DB work runs inside a single transaction; any failure rolls everything back
so the raw ``silo_status`` insert is the only permanent change until ETL succeeds.
"""

from datetime import date

from sqlalchemy import text

from database import connect_to_database
from .anomaly import _ensure_silo_anomaly_tables, _refresh_silo_anomaly_features, _refresh_silo_anomaly_events

# One shared engine for this module (created at import time)
_engine = connect_to_database()


def _run_silo_etl(snapshot_date: date) -> dict:
    """Run the full silo ETL pipeline for one snapshot date.

    Resolves all dimension keys, loads the fact table, refreshes every
    serving-layer aggregate, then triggers the anomaly detection pipeline.

    This function is intentionally a single transaction — if any step fails
    the database remains consistent with the raw ``silo_status`` rows.

    Args:
        snapshot_date: The calendar date whose CSV rows should be processed.

    Returns:
        A summary dict with row counts for each pipeline step::

            {
                "vessels_resolved":        int,  # dim rows found/created
                "fact_rows_inserted":      int,
                "anomaly_features_upserted": int,
                "anomaly_events_created":  int,
            }
    """
    # Ensure anomaly tables exist before the transaction that writes to them
    _ensure_silo_anomaly_tables(_engine)

    with _engine.begin() as conn:

        # ── 1. Resolve silo_dim_vessel ──────────────────────────────────────
        # Each distinct vessel_name in today's CSV gets a dimension key.
        vessels = conn.execute(
            text(
                """
                SELECT DISTINCT
                    vessel_name, site, vessel_type, distance_units,
                    volume_units, weight_units, vessel_height, vessel_radius,
                    vessel_length, vessel_width, hopper_height, outlet_radius,
                    outlet_length, outlet_width, capacity_volume,
                    sensor_type, sensor_address
                FROM silo_status
                WHERE snapshot_date = :sd
                  AND vessel_name IS NOT NULL
                  AND vessel_name <> ''
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        vessel_map: dict[str, int] = {}
        for v in vessels:
            existing = conn.execute(
                text(
                    "SELECT vessel_key FROM silo_dim_vessel "
                    "WHERE vessel_name = :n AND is_current = 1"
                ),
                {"n": v["vessel_name"]},
            ).fetchone()
            if existing:
                vessel_map[v["vessel_name"]] = int(existing[0])
            else:
                r = conn.execute(
                    text(
                        """
                        INSERT INTO silo_dim_vessel (
                            vessel_name, site, vessel_type, distance_units, volume_units,
                            weight_units, vessel_height, vessel_radius, vessel_length,
                            vessel_width, hopper_height, outlet_radius, outlet_length,
                            outlet_width, capacity_volume, sensor_type, sensor_address,
                            effective_from
                        ) VALUES (
                            :vessel_name, :site, :vessel_type, :distance_units, :volume_units,
                            :weight_units, :vessel_height, :vessel_radius, :vessel_length,
                            :vessel_width, :hopper_height, :outlet_radius, :outlet_length,
                            :outlet_width, :capacity_volume, :sensor_type, :sensor_address,
                            :effective_from
                        )
                        """
                    ),
                    {**dict(v), "effective_from": snapshot_date},
                )
                vessel_map[v["vessel_name"]] = int(r.lastrowid)

        # ── 2. Resolve silo_dim_contents ────────────────────────────────────
        contents_rows = conn.execute(
            text(
                """
                SELECT DISTINCT contents AS contents_code, density_units
                FROM silo_status
                WHERE snapshot_date = :sd
                  AND contents IS NOT NULL
                  AND contents <> ''
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        contents_map: dict[str, int] = {}
        for c in contents_rows:
            code = c["contents_code"] or "UNKNOWN"
            existing = conn.execute(
                text("SELECT contents_key FROM silo_dim_contents WHERE contents_code = :c"),
                {"c": code},
            ).fetchone()
            if existing:
                contents_map[code] = int(existing[0])
            else:
                r = conn.execute(
                    text(
                        "INSERT INTO silo_dim_contents (contents_code, density_units) "
                        "VALUES (:c, :d)"
                    ),
                    {"c": code, "d": c.get("density_units")},
                )
                contents_map[code] = int(r.lastrowid)

        # Ensure 'UNKNOWN' sentinel key exists for rows with no contents value
        unk = conn.execute(
            text("SELECT contents_key FROM silo_dim_contents WHERE contents_code = 'UNKNOWN'")
        ).fetchone()
        unknown_contents_key = int(unk[0]) if unk else 1
        contents_map.setdefault("UNKNOWN", unknown_contents_key)

        # ── 3. Resolve silo_dim_alarm ───────────────────────────────────────
        alarm_rows = conn.execute(
            text(
                "SELECT DISTINCT alarm_condition FROM silo_status WHERE snapshot_date = :sd"
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        alarm_map: dict[str, int] = {}
        for a in alarm_rows:
            code = (a["alarm_condition"] or "NONE").strip() or "NONE"
            if code in alarm_map:
                continue
            existing = conn.execute(
                text("SELECT alarm_key FROM silo_dim_alarm WHERE alarm_code = :c"),
                {"c": code},
            ).fetchone()
            if existing:
                alarm_map[code] = int(existing[0])
            else:
                upper = code.upper()
                severity = 2 if "ALARM" in upper else (1 if "WARN" in upper else 0)
                label = "ALARM" if severity == 2 else ("WARNING" if severity == 1 else "NONE")
                r = conn.execute(
                    text(
                        "INSERT INTO silo_dim_alarm (alarm_code, severity_level, severity_label) "
                        "VALUES (:c, :s, :l)"
                    ),
                    {"c": code, "s": severity, "l": label},
                )
                alarm_map[code] = int(r.lastrowid)

        # Ensure 'NONE' sentinel key exists
        none_alarm = conn.execute(
            text("SELECT alarm_key FROM silo_dim_alarm WHERE alarm_code = 'NONE'")
        ).fetchone()
        none_alarm_key = int(none_alarm[0]) if none_alarm else 1
        alarm_map.setdefault("NONE", none_alarm_key)

        # ── 4. Load fact_silo_status ────────────────────────────────────────
        raw_rows = conn.execute(
            text(
                """
                SELECT
                    measurement_time, snapshot_date, vessel_name, contents,
                    product_density, product_volume, product_weight, product_height,
                    headroom_volume, headroom_weight, headroom_height,
                    measurement_in_feet, measurement_in_meters, percent_full,
                    alarm_condition, source_file
                FROM silo_status
                WHERE snapshot_date = :sd
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        fact_rows = []
        for r in raw_rows:
            vk = vessel_map.get(r["vessel_name"] or "")
            if vk is None:
                # Skip rows whose vessel could not be resolved
                continue
            ck = contents_map.get(r["contents"] or "UNKNOWN", unknown_contents_key)
            ac = (r["alarm_condition"] or "NONE").strip() or "NONE"
            ak = alarm_map.get(ac, none_alarm_key)
            fact_rows.append(
                {
                    "measurement_time":    r["measurement_time"],
                    "snapshot_date":       r["snapshot_date"],
                    "time_key":            r["snapshot_date"],   # date FK into silo_dim_time
                    "vessel_key":          vk,
                    "contents_key":        ck,
                    "alarm_key":           ak,
                    "product_density":     r["product_density"],
                    "product_volume":      r["product_volume"],
                    "product_weight":      r["product_weight"],
                    "product_height":      r["product_height"],
                    "headroom_volume":     r["headroom_volume"],
                    "headroom_weight":     r["headroom_weight"],
                    "headroom_height":     r["headroom_height"],
                    "measurement_in_feet":   r["measurement_in_feet"],
                    "measurement_in_meters": r["measurement_in_meters"],
                    "percent_full":        r["percent_full"],
                    "source_file":         r["source_file"],
                }
            )

        fact_inserted = 0
        if fact_rows:
            res = conn.execute(
                text(
                    """
                    INSERT IGNORE INTO fact_silo_status (
                        measurement_time, snapshot_date, time_key,
                        vessel_key, contents_key, alarm_key,
                        product_density, product_volume, product_weight, product_height,
                        headroom_volume, headroom_weight, headroom_height,
                        measurement_in_feet, measurement_in_meters, percent_full, source_file
                    ) VALUES (
                        :measurement_time, :snapshot_date, :time_key,
                        :vessel_key, :contents_key, :alarm_key,
                        :product_density, :product_volume, :product_weight, :product_height,
                        :headroom_volume, :headroom_weight, :headroom_height,
                        :measurement_in_feet, :measurement_in_meters, :percent_full, :source_file
                    )
                    """
                ),
                fact_rows,
            )
            fact_inserted = int(res.rowcount or 0)

        # ── 5a. silo_agg_inventory_current ──────────────────────────────────
        # Stores today's latest snapshot per vessel only.
        # Rebuild from CURDATE() so uploads of historical CSVs cannot wipe
        # today's dashboard cards.
        conn.execute(
            text(
                """
                DELETE FROM silo_agg_inventory_current
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_inventory_current
                    (vessel_key, vessel_name, site, contents_code,
                     last_measurement_time, percent_full, product_weight,
                     product_height, alarm_code, severity_level, refreshed_at)
                SELECT
                    f.vessel_key, v.vessel_name, v.site, c.contents_code,
                    f.measurement_time, f.percent_full, f.product_weight,
                    f.product_height, a.alarm_code, a.severity_level, UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel   v ON v.vessel_key   = f.vessel_key
                JOIN silo_dim_contents c ON c.contents_key = f.contents_key
                JOIN silo_dim_alarm    a ON a.alarm_key    = f.alarm_key
                JOIN (
                    SELECT vessel_key, MAX(measurement_time) AS max_measurement_time
                    FROM fact_silo_status
                    WHERE snapshot_date = CURDATE()
                    GROUP BY vessel_key
                ) latest
                  ON latest.vessel_key = f.vessel_key
                 AND latest.max_measurement_time = f.measurement_time
                WHERE f.snapshot_date = CURDATE()
                """
            )
        )

        # ── 5b. silo_agg_inventory_daily ────────────────────────────────────
        # Daily aggregate per product code: avg/min/max % full, total weight.
        conn.execute(
            text("DELETE FROM silo_agg_inventory_daily WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_inventory_daily
                    (snapshot_date, contents_code, reading_count,
                     avg_percent_full, min_percent_full, max_percent_full,
                     total_product_weight, avg_product_weight, refreshed_at)
                SELECT
                    f.snapshot_date, c.contents_code, COUNT(*),
                    AVG(f.percent_full), MIN(f.percent_full), MAX(f.percent_full),
                    SUM(f.product_weight), AVG(f.product_weight), UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_contents c ON c.contents_key = f.contents_key
                WHERE f.snapshot_date = :sd
                GROUP BY f.snapshot_date, c.contents_code
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5c. silo_agg_consumption_rate ───────────────────────────────────
        # Grain: contents_code × snapshot_date (SUM across ALL silos holding
        # the same product).  Compared to previous day to get weight_delta.
        conn.execute(
            text("DELETE FROM silo_agg_consumption_rate WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_consumption_rate
                    (contents_code, snapshot_date,
                     product_weight, prev_day_weight, weight_delta,
                     avg_7d_delta, days_to_empty, refreshed_at)
                SELECT
                    c.contents_code,
                    :sd AS snapshot_date,
                    cur.total_weight  AS product_weight,
                    prev.total_weight AS prev_day_weight,
                    (cur.total_weight - COALESCE(prev.total_weight, cur.total_weight))
                        AS weight_delta,
                    NULL AS avg_7d_delta,   -- populated by anomaly feature pipeline
                    CASE
                        WHEN (cur.total_weight - COALESCE(prev.total_weight, cur.total_weight)) < 0
                        THEN ROUND(
                            ABS(cur.total_weight / NULLIF(
                                cur.total_weight - COALESCE(prev.total_weight, cur.total_weight),
                                0
                            )),
                            1
                        )
                        ELSE NULL
                    END AS days_to_empty,
                    UTC_TIMESTAMP()
                FROM (
                    -- Today's total weight per product (sum across all silos)
                    SELECT contents_key, SUM(product_weight) AS total_weight
                    FROM fact_silo_status
                    WHERE snapshot_date = :sd
                    GROUP BY contents_key
                ) cur
                JOIN silo_dim_contents c ON c.contents_key = cur.contents_key
                LEFT JOIN (
                    -- Yesterday's total weight per product
                    SELECT contents_key, SUM(product_weight) AS total_weight
                    FROM fact_silo_status
                    WHERE snapshot_date = DATE_SUB(:sd, INTERVAL 1 DAY)
                    GROUP BY contents_key
                ) prev ON prev.contents_key = cur.contents_key
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5d. silo_agg_alarm_stats ─────────────────────────────────────────
        conn.execute(
            text("DELETE FROM silo_agg_alarm_stats WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_alarm_stats
                    (vessel_key, snapshot_date, vessel_name,
                     alarm_code, severity_level, alarm_count, refreshed_at)
                SELECT
                    f.vessel_key, f.snapshot_date, v.vessel_name,
                    a.alarm_code, a.severity_level, COUNT(*), UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel v ON v.vessel_key = f.vessel_key
                JOIN silo_dim_alarm  a ON a.alarm_key  = f.alarm_key
                WHERE f.snapshot_date = :sd
                GROUP BY f.vessel_key, f.snapshot_date, v.vessel_name,
                         a.alarm_code, a.severity_level
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5e. silo_agg_silo_utilization ───────────────────────────────────
        # Monthly utilisation stats for the calendar month containing snapshot_date.
        conn.execute(
            text(
                "DELETE FROM silo_agg_silo_utilization "
                "WHERE ym = DATE_FORMAT(:sd, '%Y-%m')"
            ),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_silo_utilization
                    (vessel_key, ym, vessel_name, site, reading_count,
                     avg_percent_full, min_percent_full, max_percent_full,
                     days_above_80pct, days_below_20pct, refreshed_at)
                SELECT
                    f.vessel_key,
                    DATE_FORMAT(f.snapshot_date, '%Y-%m') AS ym,
                    v.vessel_name, v.site,
                    COUNT(*),
                    AVG(f.percent_full), MIN(f.percent_full), MAX(f.percent_full),
                    SUM(CASE WHEN f.percent_full > 80 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN f.percent_full < 20 THEN 1 ELSE 0 END),
                    UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel v ON v.vessel_key = f.vessel_key
                WHERE DATE_FORMAT(f.snapshot_date, '%Y-%m') = DATE_FORMAT(:sd, '%Y-%m')
                GROUP BY
                    f.vessel_key,
                    DATE_FORMAT(f.snapshot_date, '%Y-%m'),
                    v.vessel_name,
                    v.site
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5f. Anomaly pipeline ─────────────────────────────────────────────
        # Delegated to anomaly.py — both functions run inside this transaction.
        feature_rows = _refresh_silo_anomaly_features(conn, snapshot_date)
        event_rows   = _refresh_silo_anomaly_events(conn, snapshot_date)

    return {
        "vessels_resolved":          len(vessel_map),
        "fact_rows_inserted":        fact_inserted,
        "anomaly_features_upserted": feature_rows,
        "anomaly_events_created":    event_rows,
    }
