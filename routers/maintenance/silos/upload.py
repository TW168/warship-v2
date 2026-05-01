"""
routers/maintenance/silos/upload.py — Silos Status page and CSV upload endpoint.

Routes:
    GET  /silos-status           — Silos dashboard page (current URL)
    GET  /site-status-upload     — Legacy alias kept for backward compatibility
    POST /api/site-status/upload — Upload one Site Status CSV; parse and persist rows

CSV format
----------
The accepted file is the daily export from the SiloPatrol / Binmaster system.
Required headers are defined in ``_SITE_STATUS_REQUIRED_HEADERS``.
``Measurement Time`` must be in ``MM/DD/YYYY HH:MM:SS AM/PM`` format.

On success the endpoint:
  1. Creates ``silo_status`` table if it does not yet exist.
  2. Rejects duplicate filenames (same file may not be uploaded twice).
  3. Bulk-inserts parsed rows into ``silo_status``.
  4. Calls the full ETL pipeline (etl._run_silo_etl) which populates the
     star-schema, aggregates, and anomaly pipeline.
  5. Returns a JSON summary with row counts for every step.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from database import connect_to_database
from .anomaly import _ensure_silo_anomaly_tables
from .etl import _run_silo_etl

router = APIRouter(tags=["Silos"])

# One shared engine for this module (created at import time)
_engine = connect_to_database()

# ---------------------------------------------------------------------------
# Required CSV headers — validated on every upload
# ---------------------------------------------------------------------------
_SITE_STATUS_REQUIRED_HEADERS: set[str] = {
    "Measurement Time", "Site", "Vessel Name", "Contents", "Vessel Type",
    "Distance Units", "Volume Units", "Weight Units",
    "Vessel Height", "Vessel Radius", "Vessel Length", "Vessel Width",
    "Hopper Height", "Outlet Radius", "Outlet Length", "Outlet Width",
    "Capacity Volume", "Sensor Type", "Sensor Address",
    "Measurement in Feet", "Measurement in Meters",
    "Product Density", "Density Units",
    "Product Volume", "Product Weight", "Product Height",
    "Headroom Volume", "Headroom Weight", "Headroom Height",
    "% Full", "Alarm Condition",
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _clean_csv_text(value: str | None) -> str:
    """Trim whitespace and strip wrapping single quotes from CSV text fields.

    Some SiloPatrol exports wrap text values in single quotes, e.g. ``'AMJK'``.
    This helper strips those so the value is stored cleanly.

    Args:
        value: Raw string from csv.DictReader, or None.

    Returns:
        Cleaned string, never None.
    """
    if value is None:
        return ""
    cleaned = value.strip()
    if cleaned.startswith("'") and cleaned.endswith("'") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _parse_float_or_none(value: str | None) -> float | None:
    """Safely parse a CSV numeric field to float, returning None when blank.

    Handles comma-formatted numbers (e.g. ``"1,234.56"``).

    Args:
        value: Raw string from csv.DictReader, or None.

    Returns:
        Parsed float, or None when the field is empty / non-numeric.
    """
    raw = _clean_csv_text(value)
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _ensure_silo_status_table() -> None:
    """Create the ``silo_status`` raw-data table if it does not already exist.

    Safe to call on every upload — uses ``CREATE TABLE IF NOT EXISTS``.
    All 31 CSV columns are captured as nullable types so any future change
    to the CSV format does not break inserts of the known columns.
    """
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS silo_status (
                    id                  BIGINT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    measurement_time    DATETIME        NOT NULL,
                    site                VARCHAR(100)    NULL,
                    vessel_name         VARCHAR(100)    NULL,
                    contents            VARCHAR(100)    NULL,
                    vessel_type         VARCHAR(100)    NULL,
                    distance_units      VARCHAR(50)     NULL,
                    volume_units        VARCHAR(50)     NULL,
                    weight_units        VARCHAR(50)     NULL,
                    vessel_height       DECIMAL(18,4)   NULL,
                    vessel_radius       DECIMAL(18,4)   NULL,
                    vessel_length       DECIMAL(18,4)   NULL,
                    vessel_width        DECIMAL(18,4)   NULL,
                    hopper_height       DECIMAL(18,4)   NULL,
                    outlet_radius       DECIMAL(18,4)   NULL,
                    outlet_length       DECIMAL(18,4)   NULL,
                    outlet_width        DECIMAL(18,4)   NULL,
                    capacity_volume     DECIMAL(18,4)   NULL,
                    sensor_type         VARCHAR(150)    NULL,
                    sensor_address      VARCHAR(50)     NULL,
                    measurement_in_feet   DECIMAL(18,4) NULL,
                    measurement_in_meters DECIMAL(18,4) NULL,
                    product_density     DECIMAL(18,4)   NULL,
                    density_units       VARCHAR(50)     NULL,
                    product_volume      DECIMAL(18,4)   NULL,
                    product_weight      DECIMAL(18,4)   NULL,
                    product_height      DECIMAL(18,4)   NULL,
                    headroom_volume     DECIMAL(18,4)   NULL,
                    headroom_weight     DECIMAL(18,4)   NULL,
                    headroom_height     DECIMAL(18,4)   NULL,
                    percent_full        DECIMAL(9,4)    NULL,
                    alarm_condition     VARCHAR(120)    NULL,
                    snapshot_date       DATE            NOT NULL,
                    source_file         VARCHAR(255)    NOT NULL,
                    uploaded_at_utc     DATETIME        NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    KEY ix_silo_status_snapshot_date (snapshot_date),
                    KEY ix_silo_status_vessel_name   (vessel_name),
                    KEY ix_silo_status_source_file   (source_file)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@router.get(
    "/silos-status",
    response_class=RedirectResponse,
    summary="Silos Status Dashboard (Legacy URL)",
    description=(
        "Legacy maintenance URL. Redirects to the canonical root URL "
        "``/silos-status``."
    ),
    include_in_schema=False,
)
@router.get(
    "/site-status-upload",
    response_class=RedirectResponse,
    summary="Silos Status Dashboard (Legacy URL)",
    description=(
        "Legacy maintenance URL preserved for backward compatibility. "
        "Redirects to the canonical root URL ``/silos-status``."
    ),
    include_in_schema=False,
)
async def site_status_upload_page(request: Request) -> RedirectResponse:
    """Redirect legacy maintenance URLs to the canonical root silos page."""
    return RedirectResponse(url="/silos-status", status_code=307)


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/api/site-status/upload",
    summary="Upload Site Status CSV",
    description=(
        "Upload one Site Status CSV file exported from the SiloPatrol system. "
        "The file is parsed, validated, and inserted into ``silo_status``. "
        "Duplicate filenames are rejected with HTTP 409. "
        "On success the full ETL pipeline runs automatically, populating the "
        "star-schema and anomaly detection tables."
    ),
)
async def site_status_upload_csv(file: UploadFile = File(...)) -> JSONResponse:
    """Parse an uploaded Site Status CSV and run the silo ETL pipeline.

    Validation steps (in order):
    1. File must have a ``.csv`` extension.
    2. File must not be empty.
    3. Content must be valid UTF-8 (or UTF-8 with BOM).
    4. CSV must contain all required header columns.
    5. The filename must not already exist in ``silo_status`` (no duplicates).

    On success returns a JSON summary with row counts for every pipeline stage.

    Raises:
        HTTPException 400: Invalid file type, encoding error, missing headers,
                           or no valid data rows found.
        HTTPException 409: Filename has already been uploaded.
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        decoded = content.decode("utf-8-sig")   # strips UTF-8 BOM if present
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV encoding: {exc}") from exc

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is missing")

    missing_headers = sorted(_SITE_STATUS_REQUIRED_HEADERS - set(reader.fieldnames))
    if missing_headers:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required CSV headers: {', '.join(missing_headers)}",
        )

    rows_to_insert: list[dict] = []
    parsed_row_count = 0

    for csv_row in reader:
        parsed_row_count += 1
        measurement_time_raw = _clean_csv_text(csv_row.get("Measurement Time"))
        if not measurement_time_raw:
            continue

        try:
            measurement_time = datetime.strptime(measurement_time_raw, "%m/%d/%Y %I:%M:%S %p")
        except ValueError:
            continue

        rows_to_insert.append(
            {
                "measurement_time":      measurement_time,
                "site":                  _clean_csv_text(csv_row.get("Site")),
                "vessel_name":           _clean_csv_text(csv_row.get("Vessel Name")),
                "contents":              _clean_csv_text(csv_row.get("Contents")),
                "vessel_type":           _clean_csv_text(csv_row.get("Vessel Type")),
                "distance_units":        _clean_csv_text(csv_row.get("Distance Units")),
                "volume_units":          _clean_csv_text(csv_row.get("Volume Units")),
                "weight_units":          _clean_csv_text(csv_row.get("Weight Units")),
                "vessel_height":         _parse_float_or_none(csv_row.get("Vessel Height")),
                "vessel_radius":         _parse_float_or_none(csv_row.get("Vessel Radius")),
                "vessel_length":         _parse_float_or_none(csv_row.get("Vessel Length")),
                "vessel_width":          _parse_float_or_none(csv_row.get("Vessel Width")),
                "hopper_height":         _parse_float_or_none(csv_row.get("Hopper Height")),
                "outlet_radius":         _parse_float_or_none(csv_row.get("Outlet Radius")),
                "outlet_length":         _parse_float_or_none(csv_row.get("Outlet Length")),
                "outlet_width":          _parse_float_or_none(csv_row.get("Outlet Width")),
                "capacity_volume":       _parse_float_or_none(csv_row.get("Capacity Volume")),
                "sensor_type":           _clean_csv_text(csv_row.get("Sensor Type")),
                "sensor_address":        _clean_csv_text(csv_row.get("Sensor Address")),
                "measurement_in_feet":   _parse_float_or_none(csv_row.get("Measurement in Feet")),
                "measurement_in_meters": _parse_float_or_none(csv_row.get("Measurement in Meters")),
                "product_density":       _parse_float_or_none(csv_row.get("Product Density")),
                "density_units":         _clean_csv_text(csv_row.get("Density Units")),
                "product_volume":        _parse_float_or_none(csv_row.get("Product Volume")),
                "product_weight":        _parse_float_or_none(csv_row.get("Product Weight")),
                "product_height":        _parse_float_or_none(csv_row.get("Product Height")),
                "headroom_volume":       _parse_float_or_none(csv_row.get("Headroom Volume")),
                "headroom_weight":       _parse_float_or_none(csv_row.get("Headroom Weight")),
                "headroom_height":       _parse_float_or_none(csv_row.get("Headroom Height")),
                "percent_full":          _parse_float_or_none(csv_row.get("% Full")),
                "alarm_condition":       _clean_csv_text(csv_row.get("Alarm Condition")),
                "snapshot_date":         measurement_time.date(),
                "source_file":           filename,
            }
        )

    if not rows_to_insert:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid rows found. "
                "Confirm Measurement Time format is MM/DD/YYYY HH:MM:SS AM/PM."
            ),
        )

    # Ensure tables exist before the duplicate check and INSERT
    _ensure_silo_status_table()
    _ensure_silo_anomaly_tables(_engine)

    with _engine.begin() as conn:
        existing = conn.execute(
            text("SELECT COUNT(*) FROM silo_status WHERE source_file = :source_file"),
            {"source_file": filename},
        ).scalar()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"File '{filename}' has already been uploaded. "
                    "Each filename can only be uploaded once."
                ),
            )

        result = conn.execute(
            text(
                """
                INSERT INTO silo_status (
                    measurement_time, site, vessel_name, contents, vessel_type,
                    distance_units, volume_units, weight_units,
                    vessel_height, vessel_radius, vessel_length, vessel_width,
                    hopper_height, outlet_radius, outlet_length, outlet_width,
                    capacity_volume, sensor_type, sensor_address,
                    measurement_in_feet, measurement_in_meters, product_density,
                    density_units, product_volume, product_weight, product_height,
                    headroom_volume, headroom_weight, headroom_height,
                    percent_full, alarm_condition, snapshot_date, source_file
                ) VALUES (
                    :measurement_time, :site, :vessel_name, :contents, :vessel_type,
                    :distance_units, :volume_units, :weight_units,
                    :vessel_height, :vessel_radius, :vessel_length, :vessel_width,
                    :hopper_height, :outlet_radius, :outlet_length, :outlet_width,
                    :capacity_volume, :sensor_type, :sensor_address,
                    :measurement_in_feet, :measurement_in_meters, :product_density,
                    :density_units, :product_volume, :product_weight, :product_height,
                    :headroom_volume, :headroom_weight, :headroom_height,
                    :percent_full, :alarm_condition, :snapshot_date, :source_file
                )
                """
            ),
            rows_to_insert,
        )
        inserted_count = int(result.rowcount or 0)

    # Run the full ETL pipeline (star-schema + aggregates + anomaly detection)
    etl_result = _run_silo_etl(rows_to_insert[0]["snapshot_date"])

    return JSONResponse(
        content={
            "message":       "Site Status CSV uploaded successfully",
            "source_file":   filename,
            "csv_rows":      parsed_row_count,
            "inserted":      inserted_count,
            "snapshot_date": rows_to_insert[0]["snapshot_date"].isoformat(),
            "etl_vessels":   etl_result.get("vessels_resolved", 0),
            "etl_facts":     etl_result.get("fact_rows_inserted", 0),
            "etl_features":  etl_result.get("anomaly_features_upserted", 0),
            "etl_anomalies": etl_result.get("anomaly_events_created", 0),
        }
    )
