"""Sales Summary PDF upload and list routes.

Table: sales_summary
Routes:
    GET  /maintenance/sales-summary
    POST /maintenance/api/sales-summary/upload
    GET  /maintenance/api/sales-summary
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.sales_summary import (
    SalesSummaryListResponse,
    SalesSummaryRow,
    SalesSummaryUploadResponse,
)
from utils.sales_summary_pdf_parser import parse_sales_summary_pdf

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()


def _coerce_time(value) -> time:
    """Normalize DB TIME values into a ``datetime.time``.

    mysql-connector may return TIME as ``datetime.timedelta``.
    """
    if isinstance(value, time):
        return value
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return time(hours, minutes, seconds)
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%H:%M:%S").time()
        except ValueError:
            pass
    return time(0, 0, 0)


def _ensure_sales_summary_table() -> None:
    """Create the sales_summary table if it does not exist."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sales_summary (
                    id                          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    source_file                 VARCHAR(255) NOT NULL,
                    uploaded_at_utc             DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    job                         VARCHAR(120) NULL,
                    department                  VARCHAR(120) NULL,
                    unit                        VARCHAR(20) NULL,
                    run_date                    DATE NOT NULL,
                    business_date               DATE NOT NULL,
                    run_time                    TIME NOT NULL,
                    product_class               VARCHAR(10) NOT NULL,
                    product_name                VARCHAR(160) NOT NULL,
                    daily_order_qty             BIGINT NOT NULL,
                    daily_order_unit_price      DECIMAL(12,4) NOT NULL,
                    mtd_order_qty               BIGINT NOT NULL,
                    mtd_order_unit_price        DECIMAL(12,4) NOT NULL,
                    daily_shipment_qty          BIGINT NOT NULL,
                    daily_shipment_unit_price   DECIMAL(12,4) NOT NULL,
                    mtd_shipment_qty            BIGINT NOT NULL,
                    mtd_shipment_unit_price     DECIMAL(12,4) NOT NULL,
                    mtd_shipment_unit_frt       DECIMAL(12,4) NOT NULL,
                    monthend_backlog_qty        BIGINT NOT NULL,
                    total_backlog_qty           BIGINT NOT NULL,
                    total_backlog_unit_price    DECIMAL(12,4) NOT NULL,
                    target_qty_klb              DECIMAL(12,3) NOT NULL,
                    is_total_row                TINYINT(1) NOT NULL DEFAULT 0,
                    KEY ix_sales_summary_run_date (run_date),
                    KEY ix_sales_summary_source_file (source_file),
                    KEY ix_sales_summary_product_name (product_name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def _row_to_model(row) -> SalesSummaryRow:
    """Map one SQL row into SalesSummaryRow model."""
    return SalesSummaryRow(
        id=int(row.id),
        source_file=row.source_file,
        uploaded_at_utc=row.uploaded_at_utc,
        job=row.job,
        department=row.department,
        unit=row.unit,
        run_date=row.run_date,
        business_date=row.business_date,
        run_time=_coerce_time(row.run_time),
        product_class=row.product_class,
        product_name=row.product_name,
        daily_order_qty=int(row.daily_order_qty),
        daily_order_unit_price=float(row.daily_order_unit_price),
        mtd_order_qty=int(row.mtd_order_qty),
        mtd_order_unit_price=float(row.mtd_order_unit_price),
        daily_shipment_qty=int(row.daily_shipment_qty),
        daily_shipment_unit_price=float(row.daily_shipment_unit_price),
        mtd_shipment_qty=int(row.mtd_shipment_qty),
        mtd_shipment_unit_price=float(row.mtd_shipment_unit_price),
        mtd_shipment_unit_frt=float(row.mtd_shipment_unit_frt),
        monthend_backlog_qty=int(row.monthend_backlog_qty),
        total_backlog_qty=int(row.total_backlog_qty),
        total_backlog_unit_price=float(row.total_backlog_unit_price),
        target_qty_klb=float(row.target_qty_klb),
        is_total_row=bool(row.is_total_row),
    )


@router.get(
    "/sales-summary",
    response_class=HTMLResponse,
    summary="Sales Summary Upload Page",
    description="Maintenance page for uploading daily MKORSHDK sales summary PDFs.",
)
async def sales_summary_page(request: Request) -> HTMLResponse:
    """Render the sales summary upload page."""
    return templates.TemplateResponse(
        "maintenance/sales_summary.html",
        {"request": request, "active_page": "sales_summary"},
    )


@router.post(
    "/api/sales-summary/upload",
    response_model=SalesSummaryUploadResponse,
    summary="Upload Sales Summary PDF(s)",
    description=(
        "Upload one or more MKORSHDK PDF reports. Parsed rows are inserted into "
        "sales_summary without replacing previous uploads (history preserved)."
    ),
)
async def upload_sales_summary(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Upload and parse sales summary PDF files into sales_summary table."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one PDF file")

    _ensure_sales_summary_table()

    file_summaries: list[dict] = []
    insert_params: list[dict] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed: {filename}")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(await upload.read())
                temp_path = Path(tmp.name)

            meta, parsed_rows = parse_sales_summary_pdf(temp_path)
            if not parsed_rows:
                file_summaries.append({"file": filename, "inserted": 0, "detail": "No rows found"})
                continue

            for row in parsed_rows:
                run_date_value = meta.get("run_date") or date.today()
                business_date_value = meta.get("business_date") or (run_date_value - timedelta(days=1))
                insert_params.append(
                    {
                        "source_file": filename,
                        "job": meta.get("job"),
                        "department": meta.get("department"),
                        "unit": meta.get("unit"),
                        "run_date": run_date_value,
                        "business_date": business_date_value,
                        "run_time": meta.get("run_time"),
                        **row,
                    }
                )

            file_summaries.append(
                {
                    "file": filename,
                    "inserted": len(parsed_rows),
                    "run_date": str(meta.get("run_date") or date.today()),
                }
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if not insert_params:
        raise HTTPException(status_code=400, detail="No data rows found in uploaded file(s)")

    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO sales_summary (
                    source_file, job, department, unit, run_date, business_date, run_time,
                    product_class, product_name,
                    daily_order_qty, daily_order_unit_price,
                    mtd_order_qty, mtd_order_unit_price,
                    daily_shipment_qty, daily_shipment_unit_price,
                    mtd_shipment_qty, mtd_shipment_unit_price, mtd_shipment_unit_frt,
                    monthend_backlog_qty, total_backlog_qty, total_backlog_unit_price,
                    target_qty_klb, is_total_row, uploaded_at_utc
                ) VALUES (
                    :source_file, :job, :department, :unit, :run_date, :business_date, :run_time,
                    :product_class, :product_name,
                    :daily_order_qty, :daily_order_unit_price,
                    :mtd_order_qty, :mtd_order_unit_price,
                    :daily_shipment_qty, :daily_shipment_unit_price,
                    :mtd_shipment_qty, :mtd_shipment_unit_price, :mtd_shipment_unit_frt,
                    :monthend_backlog_qty, :total_backlog_qty, :total_backlog_unit_price,
                    :target_qty_klb, :is_total_row, UTC_TIMESTAMP()
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
    "/api/sales-summary",
    response_model=SalesSummaryListResponse,
    summary="List Sales Summary Rows",
    description="Return paginated sales_summary rows ordered by newest upload first.",
)
async def list_sales_summary(
    run_date: date | None = Query(default=None, description="Filter by run_date (YYYY-MM-DD)"),
    source_file: str | None = Query(default=None, description="Filter by source filename"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> SalesSummaryListResponse:
    """Return sales_summary rows with optional filters and pagination."""
    _ensure_sales_summary_table()

    where: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

    if run_date:
        where.append("run_date = :run_date")
        params["run_date"] = run_date
    if source_file:
        where.append("source_file LIKE :source_file")
        params["source_file"] = f"%{source_file.strip()}%"

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    count_params = {k: v for k, v in params.items() if k not in {"limit", "offset"}}

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id, source_file, uploaded_at_utc, job, department, unit,
                    run_date, business_date, run_time,
                    product_class, product_name,
                    daily_order_qty, daily_order_unit_price,
                    mtd_order_qty, mtd_order_unit_price,
                    daily_shipment_qty, daily_shipment_unit_price,
                    mtd_shipment_qty, mtd_shipment_unit_price, mtd_shipment_unit_frt,
                    monthend_backlog_qty, total_backlog_qty, total_backlog_unit_price,
                    target_qty_klb, is_total_row
                FROM sales_summary
                {where_sql}
                ORDER BY uploaded_at_utc DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).fetchall()

        total = int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM sales_summary {where_sql}"),
                count_params,
            ).scalar()
            or 0
        )

    return SalesSummaryListResponse(
        records=[_row_to_model(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


