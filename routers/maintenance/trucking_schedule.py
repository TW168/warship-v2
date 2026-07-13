"""Maintenance routes for Trucking Schedule PDF upload and listing."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.trucking_schedule import (
    TruckingScheduleListResponse,
    TruckingScheduleRow,
    TruckingScheduleUploadResponse,
)
from utils.trucking_schedule_pdf_parser import parse_trucking_schedule_pdf

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()


def _ocr_pdf_to_temp(input_pdf: Path) -> Path | None:
    """Create an OCR-processed PDF copy and return its path when successful."""
    with tempfile.NamedTemporaryFile(delete=False, suffix="_ocr.pdf") as tmp:
        output_pdf = Path(tmp.name)

    cmd = [
        "ocrmypdf",
        "--skip-text",
        "--quiet",
        str(input_pdf),
        str(output_pdf),
    ]

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        output_pdf.unlink(missing_ok=True)
        return None

    if completed.returncode != 0:
        output_pdf.unlink(missing_ok=True)
        return None

    return output_pdf


def _ensure_trucking_schedule_table() -> None:
    """Create trucking_schedule table when missing."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trucking_schedule (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    source_file VARCHAR(255) NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    bl_nbr VARCHAR(64) NULL,
                    bl_weight DECIMAL(14,3) NULL,
                    carrier_id VARCHAR(64) NULL,
                    order_nbr VARCHAR(64) NULL,
                    pk_date DATE NULL,
                    pk_time TIME NULL,
                    rt VARCHAR(32) NULL,
                    prld VARCHAR(32) NULL,
                    net_weight DECIMAL(14,3) NULL,
                    ship_to_cust VARCHAR(255) NULL,
                    st VARCHAR(10) NULL,
                    KEY ix_trucking_schedule_source_file (source_file),
                    KEY ix_trucking_schedule_pk_date (pk_date),
                    KEY ix_trucking_schedule_bl_nbr (bl_nbr)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def _row_to_model(row) -> TruckingScheduleRow:
    """Map SQL row to pydantic response model."""
    return TruckingScheduleRow(
        id=int(row.id),
        source_file=row.source_file,
        uploaded_at_utc=row.uploaded_at_utc,
        bl_nbr=row.bl_nbr,
        bl_weight=float(row.bl_weight) if row.bl_weight is not None else None,
        carrier_id=row.carrier_id,
        order_nbr=row.order_nbr,
        pk_date=row.pk_date,
        pk_time=row.pk_time,
        rt=row.rt,
        prld=row.prld,
        net_weight=float(row.net_weight) if row.net_weight is not None else None,
        ship_to_cust=row.ship_to_cust,
        st=row.st,
    )


@router.get(
    "/trucking-schedule",
    response_class=HTMLResponse,
    summary="Trucking Schedule Page",
    description="Maintenance page for uploading trucking schedule PDFs.",
)
async def trucking_schedule_page(request: Request) -> HTMLResponse:
    """Render the trucking schedule upload page."""
    _ensure_trucking_schedule_table()
    return templates.TemplateResponse(
        "maintenance/trucking_schedule.html",
        {"request": request, "active_page": "trucking_schedule"},
    )


@router.post(
    "/api/trucking-schedule/upload",
    response_model=TruckingScheduleUploadResponse,
    summary="Upload Trucking Schedule PDF",
    description=(
        "Upload one or more trucking schedule PDFs and insert parsed rows into "
        "trucking_schedule."
    ),
)
async def upload_trucking_schedule(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Upload and parse trucking schedule PDF files."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one PDF file")

    _ensure_trucking_schedule_table()

    insert_params: list[dict] = []
    file_summaries: list[dict] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed: {filename}")

        temp_path: Path | None = None
        ocr_temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(await upload.read())
                temp_path = Path(tmp.name)

            parsed_rows = parse_trucking_schedule_pdf(temp_path)
            parse_detail = "Parsed from text layer"
            if not parsed_rows:
                ocr_temp_path = _ocr_pdf_to_temp(temp_path)
                if ocr_temp_path and ocr_temp_path.exists():
                    parsed_rows = parse_trucking_schedule_pdf(ocr_temp_path)
                    if parsed_rows:
                        parse_detail = "Parsed after OCR"

            if not parsed_rows:
                file_summaries.append(
                    {
                        "file": filename,
                        "inserted": 0,
                        "detail": "No data rows found after text parse and OCR.",
                    }
                )
                continue

            for row in parsed_rows:
                insert_params.append({"source_file": filename, **row})

            file_summaries.append(
                {
                    "file": filename,
                    "inserted": len(parsed_rows),
                    "detail": parse_detail,
                }
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            if ocr_temp_path and ocr_temp_path.exists():
                ocr_temp_path.unlink(missing_ok=True)

    if not insert_params:
        raise HTTPException(
            status_code=400,
            detail="No data rows were parsed from the uploaded PDF file(s).",
        )

    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO trucking_schedule (
                    source_file,
                    bl_nbr, bl_weight, carrier_id, order_nbr, pk_date, pk_time,
                    rt, prld, net_weight, ship_to_cust, st, uploaded_at_utc
                ) VALUES (
                    :source_file,
                    :bl_nbr, :bl_weight, :carrier_id, :order_nbr, :pk_date, :pk_time,
                    :rt, :prld, :net_weight, :ship_to_cust, :st, UTC_TIMESTAMP()
                )
                """
            ),
            insert_params,
        )
        inserted = int(result.rowcount or 0)

    return JSONResponse(
        {
            "message": f"Inserted {inserted} rows from {len(file_summaries)} file(s)",
            "inserted": inserted,
            "files": file_summaries,
        }
    )


@router.get(
    "/api/trucking-schedule",
    response_model=TruckingScheduleListResponse,
    summary="List Trucking Schedule Rows",
    description="Returns paginated trucking_schedule rows ordered by latest upload.",
)
async def list_trucking_schedule(
    source_file: str | None = Query(default=None, description="Filter by source filename"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> TruckingScheduleListResponse:
    """Return trucking schedule records with optional filename filter."""
    _ensure_trucking_schedule_table()

    where_parts: list[str] = []
    params: dict = {"limit": limit, "offset": offset}
    if source_file:
        where_parts.append("source_file LIKE :source_file")
        params["source_file"] = f"%{source_file.strip()}%"

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id, source_file, uploaded_at_utc,
                    bl_nbr, bl_weight, carrier_id, order_nbr, pk_date, pk_time,
                    rt, prld, net_weight, ship_to_cust, st
                FROM trucking_schedule
                {where_sql}
                ORDER BY uploaded_at_utc DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).fetchall()

        total = int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM trucking_schedule {where_sql}"),
                {k: v for k, v in params.items() if k not in {"limit", "offset"}},
            ).scalar()
            or 0
        )

    return TruckingScheduleListResponse(
        records=[_row_to_model(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
