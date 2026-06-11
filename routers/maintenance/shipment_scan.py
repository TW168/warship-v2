"""
routers/maintenance/shipment_scan.py -- Shipment Scan upload and management.

Table: shipment_scan
Columns: id, uploaded_at, source_file, file_size, status, created_at,
         scan_datetime, pallet, bol, name

Routes:
    GET  /shipment-scan              -- Shipment scan management page
    POST /api/shipment-scan/upload   -- Upload shipment scan files (.xlsx / .csv)
    GET  /api/shipment-scan          -- List uploads (grouped one row per file)
"""

import csv
import io
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import openpyxl
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger
from schemas.shipment_scan import (
    ShipmentScanDailyBolResponse,
    ShipmentScanListResponse,
    ShipmentScanUploadResponse,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()
logger = get_router_logger("maintenance.shipment_scan")

_TEXAS_TZ = ZoneInfo("America/Chicago")

# Maps normalised Excel/CSV header -> actual DB column
_COLUMN_MAP = {
    "date":   "scan_datetime",
    "pallet": "pallet",
    "bol":    "bol",
    "status": "status",
    "name":   "name",
}


def _texas_now() -> datetime:
    """Current Texas wall-clock time (CST/CDT) as naive datetime for MySQL DATETIME."""
    return datetime.now(_TEXAS_TZ).replace(tzinfo=None)


def _parse_dt(value) -> Optional[datetime]:
    """Parse date/datetime from Excel cell or string into naive datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "year") and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%y %H:%M:%S",
            "%m/%d/%y %H:%M",
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
        ):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def _rows_from_excel(content: bytes, uploaded_at: datetime, filename: str) -> list[dict]:
    """Parse XLSX and return list of row dicts with only real DB columns."""
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = list(next(rows_iter))

    col_map: dict[int, str] = {}
    for i, h in enumerate(raw_headers):
        if h is None:
            continue
        key = str(h).lower().strip()
        if key in _COLUMN_MAP:
            col_map[i] = _COLUMN_MAP[key]
            logger.info("XLSX col %d '%s' -> '%s'", i, h, _COLUMN_MAP[key])
        else:
            logger.debug("XLSX col %d '%s' not mapped", i, h)

    records = []
    for raw_row in rows_iter:
        if not any(raw_row):
            continue
        rec: dict = {"uploaded_at": uploaded_at, "source_file": filename}
        for idx, db_col in col_map.items():
            val = raw_row[idx] if idx < len(raw_row) else None
            rec[db_col] = _parse_dt(val) if db_col == "scan_datetime" else (
                str(val).strip() if val is not None else None
            )
        records.append(rec)

    wb.close()
    return records


def _rows_from_csv(content: bytes, uploaded_at: datetime, filename: str) -> list[dict]:
    """Parse CSV and return list of row dicts with only real DB columns."""
    text_content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_content))

    col_map: dict[str, str] = {}
    if reader.fieldnames:
        for h in reader.fieldnames:
            key = str(h).lower().strip()
            if key in _COLUMN_MAP:
                col_map[h] = _COLUMN_MAP[key]

    records = []
    for row in reader:
        if not any(row.values()):
            continue
        rec: dict = {"uploaded_at": uploaded_at, "source_file": filename}
        for csv_col, db_col in col_map.items():
            val = row.get(csv_col)
            rec[db_col] = _parse_dt(val) if db_col == "scan_datetime" else (
                str(val).strip() if val else None
            )
        records.append(rec)

    return records


@router.get(
    "/shipment-scan",
    response_class=HTMLResponse,
    summary="Shipment Scan management page",
    description="Upload and manage shipment scan documents.",
)
async def shipment_scan_page(request: Request) -> HTMLResponse:
    """Render the shipment scan upload and management page."""
    return templates.TemplateResponse(
        "maintenance/shipment_scan.html",
        {"request": request, "active_page": "shipment_scan"},
    )


@router.post(
    "/api/shipment-scan/upload",
    response_model=ShipmentScanUploadResponse,
    summary="Upload shipment scan file",
    description="Upload and process an Excel (.xlsx) or CSV shipment scan file.",
)
async def upload_shipment_scan(file: UploadFile = File(...)) -> JSONResponse:
    """Parse XLSX/CSV file and insert rows into shipment_scan table."""
    if not file.filename:
        return JSONResponse(status_code=400, content={"error": "No filename provided."})

    fname_lower = file.filename.lower()
    if not fname_lower.endswith((".xlsx", ".xls", ".csv")):
        return JSONResponse(status_code=422, content={"error": "Only .xlsx or .csv files accepted."})

    try:
        content = await file.read()
        file_size = len(content)
        uploaded_at = _texas_now()

        with _engine.connect() as conn:
            dup = conn.execute(
                text("SELECT 1 FROM shipment_scan WHERE source_file = :f AND file_size = :s LIMIT 1"),
                {"f": file.filename, "s": file_size},
            ).fetchone()
            if dup:
                return JSONResponse(content={"status": "duplicate", "message": "File already uploaded.", "rows_inserted": 0})

        if fname_lower.endswith((".xlsx", ".xls")):
            records = _rows_from_excel(content, uploaded_at, file.filename)
        else:
            records = _rows_from_csv(content, uploaded_at, file.filename)

        if not records:
            return JSONResponse(content={"status": "ok", "message": "No data rows found.", "rows_inserted": 0})

        with _engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO shipment_scan
                        (uploaded_at, source_file, file_size, scan_datetime, pallet, bol, status, name)
                    VALUES
                        (:uploaded_at, :source_file, :file_size,
                         :scan_datetime, :pallet, :bol, :status, :name)
                """),
                [
                    {
                        "uploaded_at":   r.get("uploaded_at"),
                        "source_file":   r.get("source_file"),
                        "file_size":     file_size,
                        "scan_datetime": r.get("scan_datetime"),
                        "pallet":        r.get("pallet"),
                        "bol":           r.get("bol"),
                        "status":        r.get("status"),
                        "name":          r.get("name"),
                    }
                    for r in records
                ],
            )
            conn.commit()

        logger.info("Inserted %d rows from '%s'", len(records), file.filename)
        return JSONResponse(content={"status": "ok", "message": f"Processed {file.filename}", "rows_inserted": len(records)})

    except Exception as exc:
        logger.error("Upload failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Upload failed: {exc}"})


@router.get(
    "/api/shipment-scan",
    response_model=ShipmentScanListResponse,
    summary="List shipment scan records",
    description="Returns one row per uploaded file with context summary.",
)
async def list_shipment_scan(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source_file: Optional[str] = Query(default=None),
) -> JSONResponse:
    """List uploaded shipment scan files grouped by upload event."""
    try:
        where_clauses = []
        params: dict = {"limit": limit, "offset": offset}

        if source_file:
            where_clauses.append("source_file LIKE :source_file")
            params["source_file"] = f"%{source_file}%"

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}

        with _engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT
                        MIN(id)            AS id,
                        MAX(uploaded_at)   AS uploaded_at,
                        source_file,
                        file_size,
                        COUNT(*)           AS row_count,
                        MAX(scan_datetime) AS scan_datetime,
                        MAX(pallet)        AS pallet,
                        MAX(bol)           AS bol,
                        MAX(status)        AS status,
                        MAX(name)          AS name,
                        MAX(created_at)    AS created_at
                    FROM shipment_scan
                    {where_sql}
                    GROUP BY source_file, file_size
                    ORDER BY MAX(uploaded_at) DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            ).fetchall()

            total = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM (
                        SELECT source_file FROM shipment_scan {where_sql}
                        GROUP BY source_file, file_size
                    ) g
                """),
                count_params,
            ).scalar()

        records = [
            {
                "id":            row.id,
                "uploaded_at":   row.uploaded_at.isoformat() if row.uploaded_at else None,
                "source_file":   row.source_file,
                "file_size":     row.file_size,
                "row_count":     row.row_count,
                "scan_datetime": row.scan_datetime.isoformat() if row.scan_datetime else None,
                "pallet":        row.pallet,
                "bol":           row.bol,
                "status":        row.status,
                "name":          row.name,
            }
            for row in rows
        ]

        return JSONResponse({"records": records, "total": total, "limit": limit, "offset": offset})

    except Exception as exc:
        logger.error("List failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Failed to retrieve records: {exc}"})


@router.get(
    "/api/shipment-scan/daily-bol",
    response_model=ShipmentScanDailyBolResponse,
    summary="Daily shipment scan BOL trend",
    description=(
        "Returns daily distinct BOL counts from shipment_scan grouped by scan date "
        "for line-chart rendering."
    ),
)
async def shipment_scan_daily_bol() -> JSONResponse:
    """Return daily distinct BOL counts for the shipment scan trend chart."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        DATE(scan_datetime) AS scan_date,
                        COUNT(DISTINCT bol) AS bol_count
                    FROM shipment_scan
                    GROUP BY DATE(scan_datetime)
                    ORDER BY scan_date
                    """
                )
            ).fetchall()

            total_unique_bols = conn.execute(
                text("SELECT COUNT(DISTINCT bol) FROM shipment_scan")
            ).scalar() or 0

        series = [
            {
                "scan_date": row.scan_date.isoformat() if row.scan_date else "Unknown",
                "bol_count": int(row.bol_count or 0),
            }
            for row in rows
            if row.scan_date is not None
        ]

        return JSONResponse(
            {
                "series": series,
                "total_days": len(series),
                "total_unique_bols": int(total_unique_bols),
            }
        )
    except Exception as exc:
        logger.error("Daily BOL trend query failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Failed to load trend: {exc}"})
