"""AMIN daily shipment summary PDF upload and MySQL storage."""

from __future__ import annotations

import re
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy import text

from database import connect_to_database
from schemas.amin_daily_shipment_summary import (
    AminDailyShipmentSummaryMonthResponse,
    AminDailyShipmentSummaryMonthlyPoint,
    AminDailyShipmentSummaryPeriod,
    AminDailyShipmentSummaryRecord,
    AminDailyShipmentSummaryUploadResponse,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

_HEADER_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s+PAGE\s+(\d+)$",
    re.IGNORECASE,
)
_QUANTITY = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_MONEY = rf"{_QUANTITY}\.\d{{2}}"
_RATE = rf"{_QUANTITY}\.\d{{4}}"
_DETAIL_RE = re.compile(
    rf"^(\d{{2}}/\d{{2}}/\d{{2}})\s+({_QUANTITY})\s+({_MONEY})\s+({_RATE})\s+({_QUANTITY})$"
)
_TOTAL_RE = re.compile(rf"^({_QUANTITY})\s+({_MONEY})\s+({_RATE})\s+({_QUANTITY})$")


def _ensure_amin_daily_shipment_summary_table() -> None:
    """Create the report-line table when it is first needed."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS amin_daily_shipment_summary (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    report_generated_at DATETIME NOT NULL,
                    report_name VARCHAR(255) NOT NULL,
                    page_number INT NOT NULL,
                    pdf_page_count INT NOT NULL,
                    line_number INT NOT NULL,
                    row_type VARCHAR(10) NOT NULL,
                    ship_date DATE NULL,
                    qty_shipped BIGINT NULL,
                    freight_total DECIMAL(15,2) NULL,
                    avg_frt_cent_lb DECIMAL(12,4) NULL,
                    shipped_avg BIGINT NULL,
                    source_file VARCHAR(255) NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    UNIQUE KEY ux_amin_shipment_report_line
                        (report_generated_at, page_number, line_number),
                    KEY ix_amin_shipment_report_date (report_generated_at),
                    KEY ix_amin_shipment_ship_date (ship_date),
                    KEY ix_amin_shipment_source_file (source_file)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def _parse_amin_daily_shipment_text_pages(
    page_texts: list[str],
) -> tuple[dict, list[dict]]:
    """Parse header metadata and shipment detail/aggregate lines from PDF text."""
    if not page_texts:
        raise ValueError("The PDF contains no pages.")

    report_metadata: dict | None = None
    records: list[dict] = []

    for page_index, page_text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        header_match = next(
            (match for line in lines if (match := _HEADER_RE.fullmatch(line))),
            None,
        )
        if header_match is None:
            if page_index == 1:
                raise ValueError("The PDF is missing the expected AMIN report header.")
            raise ValueError(f"Page {page_index} is missing the expected report header.")

        generated_at = datetime.strptime(
            f"{header_match.group(1)} {header_match.group(2)}", "%m/%d/%y %H:%M:%S"
        )
        report_name = header_match.group(3).strip()
        if not report_name.casefold().startswith("amin daily shipment summary"):
            raise ValueError("The uploaded PDF is not an AMIN daily shipment summary.")

        if report_metadata is None:
            report_metadata = {
                "report_generated_at": generated_at,
                "report_name": report_name,
                "pdf_page_count": len(page_texts),
            }
        elif (
            generated_at != report_metadata["report_generated_at"]
            or report_name != report_metadata["report_name"]
        ):
            raise ValueError("Report header metadata is inconsistent across PDF pages.")

        page_number = int(header_match.group(4))
        line_number = 0
        for line in lines:
            detail_match = _DETAIL_RE.fullmatch(line)
            if detail_match is not None:
                ship_date = datetime.strptime(detail_match.group(1), "%y/%m/%d").date()
                values = detail_match.groups()[1:]
                row_type = "detail"
            else:
                total_match = _TOTAL_RE.fullmatch(line)
                if total_match is None:
                    continue
                ship_date = None
                values = total_match.groups()
                row_type = "total"

            line_number += 1
            records.append(
                {
                    "report_generated_at": generated_at,
                    "report_name": report_name,
                    "page_number": page_number,
                    "pdf_page_count": len(page_texts),
                    "line_number": line_number,
                    "row_type": row_type,
                    "ship_date": ship_date,
                    "qty_shipped": int(values[0].replace(",", "")),
                    "freight_total": Decimal(values[1].replace(",", "")),
                    "avg_frt_cent_lb": Decimal(values[2].replace(",", "")),
                    "shipped_avg": int(values[3].replace(",", "")),
                }
            )

    if not any(record["row_type"] == "detail" for record in records):
        raise ValueError("No shipment detail rows were found in the PDF.")
    if report_metadata is None:
        raise ValueError("The PDF is missing report metadata.")

    return report_metadata, records


def _parse_amin_daily_shipment_pdf(pdf_path: Path) -> tuple[dict, list[dict]]:
    """Extract text from each page and parse an AMIN daily shipment summary."""
    with pdfplumber.open(pdf_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
    return _parse_amin_daily_shipment_text_pages(page_texts)


@router.get(
    "/amin-daily-shipment-summary",
    response_class=HTMLResponse,
    summary="AMIN Daily Shipment Summary Upload Page",
    description=(
        "Upload the daily AMIN shipment summary PDF and store its shipment lines "
        "and printed report metadata in amin_daily_shipment_summary."
    ),
)
async def amin_daily_shipment_summary_page(request: Request) -> HTMLResponse:
    """Create the destination table if needed and render its upload page."""
    _ensure_amin_daily_shipment_summary_table()
    return templates.TemplateResponse(
        request,
        "maintenance/amin_daily_shipment_summary.html",
        {"active_page": "amin_daily_shipment_summary"},
    )


@router.post(
    "/api/amin-daily-shipment-summary/upload",
    response_model=AminDailyShipmentSummaryUploadResponse,
    summary="Upload AMIN Daily Shipment Summary PDF",
    description=(
        "Parse the report header, shipment detail lines, and printed aggregate "
        "line into amin_daily_shipment_summary. Re-uploading the same report "
        "timestamp replaces its prior rows."
    ),
)
async def upload_amin_daily_shipment_summary(
    file: UploadFile = File(...),
) -> AminDailyShipmentSummaryUploadResponse:
    """Parse one report PDF and replace rows for that report timestamp."""
    original_filename = (file.filename or "").strip()
    filename = original_filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")
    if not filename or len(filename) > 255:
        raise HTTPException(status_code=400, detail="The PDF filename must be 1-255 characters.")

    _ensure_amin_daily_shipment_summary_table()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            temp_path = Path(tmp.name)

        try:
            metadata, records = _parse_amin_daily_shipment_pdf(temp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PdfminerException as exc:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file could not be read as a valid PDF.",
            ) from exc

        for record in records:
            record["source_file"] = filename

        with _engine.begin() as conn:
            conn.execute(
                text(
                    """
                    DELETE FROM amin_daily_shipment_summary
                    WHERE report_generated_at = :report_generated_at
                    """
                ),
                {"report_generated_at": metadata["report_generated_at"]},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO amin_daily_shipment_summary (
                        report_generated_at, report_name, page_number, pdf_page_count,
                        line_number, row_type, ship_date, qty_shipped, freight_total,
                        avg_frt_cent_lb, shipped_avg, source_file
                    ) VALUES (
                        :report_generated_at, :report_name, :page_number, :pdf_page_count,
                        :line_number, :row_type, :ship_date, :qty_shipped, :freight_total,
                        :avg_frt_cent_lb, :shipped_avg, :source_file
                    )
                    """
                ),
                records,
            )
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return AminDailyShipmentSummaryUploadResponse(
        message=f"Stored {len(records)} rows from {filename}.",
        file=filename,
        report_generated_at=metadata["report_generated_at"],
        report_name=metadata["report_name"],
        pdf_page_count=metadata["pdf_page_count"],
        detail_rows=sum(record["row_type"] == "detail" for record in records),
        total_rows=sum(record["row_type"] == "total" for record in records),
        inserted_rows=len(records),
    )


@router.get(
    "/api/amin-daily-shipment-summary/periods",
    response_model=list[AminDailyShipmentSummaryPeriod],
    summary="List AMIN Shipment Report Months",
    description="Return year/month choices based on report generation timestamps.",
)
async def list_amin_daily_shipment_summary_periods() -> list[AminDailyShipmentSummaryPeriod]:
    """Return available report year/month choices, newest first."""
    _ensure_amin_daily_shipment_summary_table()
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT
                    YEAR(report_generated_at) AS report_year,
                    MONTH(report_generated_at) AS report_month
                FROM amin_daily_shipment_summary
                ORDER BY report_year DESC, report_month DESC
                """
            )
        ).mappings().all()

    return [
        AminDailyShipmentSummaryPeriod(year=int(row["report_year"]), month=int(row["report_month"]))
        for row in rows
    ]


@router.get(
    "/api/amin-daily-shipment-summary/data",
    response_model=AminDailyShipmentSummaryMonthResponse,
    summary="Get Latest AMIN Shipment Report for Month",
    description=(
        "Return the latest generated report snapshot for the selected report year "
        "and month, including detail rows and its printed aggregate row."
    ),
)
async def get_amin_daily_shipment_summary_month(
    year: int = Query(..., ge=2000, le=2100, description="Report generation year"),
    month: int = Query(..., ge=1, le=12, description="Report generation month"),
) -> AminDailyShipmentSummaryMonthResponse:
    """Return the latest uploaded report snapshot for the requested month."""
    _ensure_amin_daily_shipment_summary_table()
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    id, report_generated_at, report_name, page_number, pdf_page_count,
                    line_number, row_type, ship_date, qty_shipped, freight_total,
                    avg_frt_cent_lb, shipped_avg, source_file
                FROM amin_daily_shipment_summary
                WHERE report_generated_at = (
                    SELECT MAX(report_generated_at)
                    FROM amin_daily_shipment_summary
                    WHERE YEAR(report_generated_at) = :year
                      AND MONTH(report_generated_at) = :month
                )
                ORDER BY page_number, line_number
                """
            ),
            {"year": year, "month": month},
        ).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No AMIN shipment report is available for {year}-{month:02d}.",
        )

    records = [
        AminDailyShipmentSummaryRecord.model_validate(dict(row))
        for row in rows
    ]
    report = records[0]
    return AminDailyShipmentSummaryMonthResponse(
        year=year,
        month=month,
        report_generated_at=report.report_generated_at,
        report_name=report.report_name,
        pdf_page_count=report.pdf_page_count,
        records=records,
    )


@router.get(
    "/api/amin-daily-shipment-summary/monthly-trend",
    response_model=list[AminDailyShipmentSummaryMonthlyPoint],
    summary="Get AMIN Shipment Monthly Trend",
    description=(
        "Return Qty Shipped (lbs, as confirmed by the user) and average freight from "
        "the aggregate row of the latest generated report for each year/month."
    ),
)
async def get_amin_daily_shipment_summary_monthly_trend() -> list[AminDailyShipmentSummaryMonthlyPoint]:
    """Return monthly aggregate Qty Shipped in lbs and freight, independent of selectors."""
    _ensure_amin_daily_shipment_summary_table()
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    latest.report_year AS year,
                    latest.report_month AS month,
                    summary.report_generated_at,
                    summary.report_name,
                    summary.page_number,
                    summary.line_number,
                    summary.qty_shipped,
                    summary.avg_frt_cent_lb
                FROM amin_daily_shipment_summary AS summary
                JOIN (
                    SELECT
                        YEAR(report_generated_at) AS report_year,
                        MONTH(report_generated_at) AS report_month,
                        MAX(report_generated_at) AS latest_report_generated_at
                    FROM amin_daily_shipment_summary
                    GROUP BY YEAR(report_generated_at), MONTH(report_generated_at)
                ) AS latest
                  ON YEAR(summary.report_generated_at) = latest.report_year
                 AND MONTH(summary.report_generated_at) = latest.report_month
                 AND summary.report_generated_at = latest.latest_report_generated_at
                WHERE summary.row_type = 'total'
                ORDER BY
                    latest.report_year,
                    latest.report_month,
                    summary.page_number DESC,
                    summary.line_number DESC
                """
            )
        ).mappings().all()

    monthly_points: list[AminDailyShipmentSummaryMonthlyPoint] = []
    seen_periods: set[tuple[int, int]] = set()
    for row in rows:
        period = (int(row["year"]), int(row["month"]))
        if period in seen_periods:
            continue
        seen_periods.add(period)
        monthly_points.append(
            AminDailyShipmentSummaryMonthlyPoint(
                year=period[0],
                month=period[1],
                report_generated_at=row["report_generated_at"],
                report_name=row["report_name"],
                qty_shipped=int(row["qty_shipped"]),
                avg_frt_cent_lb=row["avg_frt_cent_lb"],
            )
        )

    return monthly_points
