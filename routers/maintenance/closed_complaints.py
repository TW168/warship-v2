"""Closed complaints Excel upload routes.

Table: closed_complaints
Routes:
    GET  /maintenance/closed-complaints
    POST /maintenance/api/closed-complaints/upload
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl
import xlrd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger
from schemas.closed_complaints import (
    ClosedComplaintsCodeOption,
    ClosedComplaintsCodeSummaryOptionsResponse,
    ClosedComplaintsCodeSummaryResponse,
    ClosedComplaintsCodeSummaryRow,
    ClosedComplaintsTrendPoint,
    ClosedComplaintsTrendResponse,
    ClosedComplaintsSummaryResponse,
    ClosedComplaintsSummaryRow,
    ClosedComplaintsUploadResponse,
    ClosedComplaintsYearOption,
    ClosedComplaintsYearsResponse,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()
logger = get_router_logger("maintenance.closed_complaints")

_PRODUCT_GROUP_SALES_SUMMARY_MAP = {
    "CT": {"product_class": "", "product_name_normalized": "CONCENTRATTTL"},
    "BP": {"product_class": "BOPP", "product_name_normalized": "TTL"},
    "SW": {"product_class": "STRETCH", "product_name_normalized": "WRTTL"},
    "IS": {"product_class": "ISCC", "product_name_normalized": "TTL"},
    "SC": {"product_class": "SC", "product_name_normalized": "TTL"},
}

_HEADER_MAP = {
    "complaint": "complaint_no",
    "code": "code",
    "invoice": "invoice_no",
    "seq": "seq",
    "order": "order_no",
    "customer": "customer",
    "dt_complaint": "dt_complaint",
    "amt_claim": "amt_claim",
    "return": "return_flag",
    "prod_group": "prod_group",
    "desc": "description",
    "qty_claim": "qty_claim",
    "close": "close_flag",
    "dt_approved": "dt_approved",
    "amt_approved": "amt_approved",
    "plant": "plant",
    "csc": "csc",
    "closing_text": "closing_text",
    "salesrep": "sales_rep",
    "prodtype": "prod_type",
    "ccar_costcenter": "ccar_cost_center",
    "shipto": "ship_to",
    "invoice_amt": "invoice_amt",
    "sort_code": "sort_code",
    "tx_code": "tx_code",
    "confirm_to": "confirm_to",
}

_KEY_FIELDS = ("complaint_no", "invoice_no", "order_no", "seq")


def _ensure_closed_complaints_table() -> None:
    """Create the closed_complaints table if it does not exist."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS closed_complaints (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    complaint_no VARCHAR(32) NOT NULL,
                    code VARCHAR(16) NULL,
                    invoice_no VARCHAR(32) NOT NULL,
                    seq VARCHAR(8) NOT NULL,
                    order_no VARCHAR(32) NOT NULL,
                    customer VARCHAR(255) NULL,
                    dt_complaint DATE NULL,
                    amt_claim DECIMAL(14, 2) NULL,
                    return_flag VARCHAR(8) NULL,
                    prod_group VARCHAR(16) NULL,
                    description TEXT NULL,
                    qty_claim DECIMAL(14, 2) NULL,
                    close_flag VARCHAR(8) NULL,
                    dt_approved DATE NULL,
                    amt_approved DECIMAL(14, 2) NULL,
                    plant VARCHAR(32) NULL,
                    csc VARCHAR(32) NULL,
                    closing_text TEXT NULL,
                    sales_rep VARCHAR(64) NULL,
                    prod_type VARCHAR(64) NULL,
                    ccar_cost_center VARCHAR(64) NULL,
                    ship_to VARCHAR(255) NULL,
                    invoice_amt DECIMAL(14, 2) NULL,
                    sort_code VARCHAR(32) NULL,
                    tx_code VARCHAR(32) NULL,
                    confirm_to VARCHAR(128) NULL,
                    source_file VARCHAR(255) NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    UNIQUE KEY uq_closed_complaints_business_key (complaint_no, invoice_no, order_no, seq),
                    KEY ix_closed_complaints_dt_complaint (dt_complaint),
                    KEY ix_closed_complaints_source_file (source_file)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def _sales_summary_table_exists() -> bool:
    """Return whether the sales_summary table exists in the current database."""
    with _engine.connect() as conn:
        exists = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name = 'sales_summary'
                """
            )
        ).scalar()
    return bool(exists)


def _normalize_header(value: Any) -> str:
    """Normalize spreadsheet headers for stable field matching."""
    header = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return header.strip("_")


def _parse_date(value: Any) -> date | None:
    """Parse a date cell or mm/dd/yyyy string into a date."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Invalid date value: {value!r}")


def _parse_decimal(value: Any) -> Decimal | None:
    """Parse numbers from Excel cells or strings into Decimal."""
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc


def _parse_text(value: Any) -> str | None:
    """Normalize text cells, preserving empty values as None."""
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _validate_headers(mapped_columns: dict[int, str]) -> None:
    """Validate that the required business-key and date headers are present."""
    missing_headers = [
        original for original, mapped in (
            ("Complaint#", "complaint_no"),
            ("Invoice", "invoice_no"),
            ("Seq", "seq"),
            ("Order#", "order_no"),
            ("DT Complaint", "dt_complaint"),
        )
        if mapped not in mapped_columns.values()
    ]
    if missing_headers:
        raise ValueError(f"Missing required header(s): {', '.join(missing_headers)}")


def _row_to_record(raw_row: list[Any] | tuple[Any, ...], mapped_columns: dict[int, str], row_num: int, filename: str) -> dict[str, Any] | None:
    """Convert one worksheet row into a DB-ready record dict."""
    if not any(cell not in (None, "") for cell in raw_row):
        return None

    record: dict[str, Any] = {"source_file": filename}
    for idx, field_name in mapped_columns.items():
        value = raw_row[idx] if idx < len(raw_row) else None

        if field_name in {"dt_complaint", "dt_approved"}:
            record[field_name] = _parse_date(value)
        elif field_name in {"amt_claim", "qty_claim", "amt_approved", "invoice_amt"}:
            record[field_name] = _parse_decimal(value)
        else:
            record[field_name] = _parse_text(value)

    for key_field in _KEY_FIELDS:
        if not record.get(key_field):
            raise ValueError(f"Missing required key field '{key_field}' in worksheet row {row_num}.")

    return record


def _rows_from_xlsx(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Read one XLSX file and convert rows into DB-ready dictionaries."""
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    worksheet = workbook.active
    rows_iter = worksheet.iter_rows(values_only=True)

    try:
        raw_headers = next(rows_iter)
    except StopIteration as exc:
        workbook.close()
        raise ValueError("The workbook is empty.") from exc

    mapped_columns: dict[int, str] = {}
    for idx, header in enumerate(raw_headers):
        normalized = _normalize_header(header)
        if normalized in _HEADER_MAP:
            mapped_columns[idx] = _HEADER_MAP[normalized]

    _validate_headers(mapped_columns)

    parsed_rows: list[dict[str, Any]] = []
    for excel_row_num, raw_row in enumerate(rows_iter, start=2):
        record = _row_to_record(raw_row, mapped_columns, excel_row_num, filename)
        if record is not None:
            parsed_rows.append(record)

    workbook.close()
    return parsed_rows


def _rows_from_xls(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Read one legacy XLS file and convert rows into DB-ready dictionaries."""
    workbook = xlrd.open_workbook(file_contents=content)
    worksheet = workbook.sheet_by_index(0)

    if worksheet.nrows == 0:
        raise ValueError("The workbook is empty.")

    raw_headers = worksheet.row_values(0)
    mapped_columns: dict[int, str] = {}
    for idx, header in enumerate(raw_headers):
        normalized = _normalize_header(header)
        if normalized in _HEADER_MAP:
            mapped_columns[idx] = _HEADER_MAP[normalized]

    _validate_headers(mapped_columns)

    datemode = workbook.datemode
    parsed_rows: list[dict[str, Any]] = []
    for row_idx in range(1, worksheet.nrows):
        raw_row = list(worksheet.row_values(row_idx))
        for col_idx, cell in enumerate(worksheet.row(row_idx)):
            if cell.ctype == xlrd.XL_CELL_DATE:
                raw_row[col_idx] = xlrd.xldate.xldate_as_datetime(cell.value, datemode)

        record = _row_to_record(raw_row, mapped_columns, row_idx + 1, filename)
        if record is not None:
            parsed_rows.append(record)

    return parsed_rows


@router.get(
    "/closed-complaints",
    response_class=HTMLResponse,
    summary="Closed Complaints upload page",
    description="Maintenance page for uploading closed complaints Excel files into MySQL.",
)
async def closed_complaints_page(request: Request) -> HTMLResponse:
    """Render the closed complaints upload page."""
    _ensure_closed_complaints_table()
    return templates.TemplateResponse(
        "maintenance/closed_complaints.html",
        {"request": request, "active_page": "closed_complaints"},
    )


@router.get(
    "/api/closed-complaints/years",
    response_model=ClosedComplaintsYearsResponse,
    summary="List closed complaints years",
    description="Return distinct complaint years from dt_complaint for the summary filter dropdown.",
)
async def closed_complaints_years() -> ClosedComplaintsYearsResponse:
    """Return distinct complaint years for the summary filter."""
    _ensure_closed_complaints_table()

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT YEAR(dt_complaint) AS complaint_year
                FROM closed_complaints
                WHERE dt_complaint IS NOT NULL
                ORDER BY complaint_year DESC
                """
            )
        ).fetchall()

    return ClosedComplaintsYearsResponse(
        years=[ClosedComplaintsYearOption(year=int(row.complaint_year)) for row in rows if row.complaint_year is not None]
    )


@router.get(
    "/api/closed-complaints/summary",
    response_model=ClosedComplaintsSummaryResponse,
    summary="Closed complaints summary by product group",
    description="Return complaint summary grouped by product group with an optional year filter.",
)
async def closed_complaints_summary(
    year: int | None = Query(default=None, ge=1900, le=2100, description="Filter summary by complaint year"),
) -> ClosedComplaintsSummaryResponse:
    """Return a grouped closed complaints summary by product group."""
    _ensure_closed_complaints_table()

    if not _sales_summary_table_exists():
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        COALESCE(NULLIF(prod_group, ''), 'Unknown') AS prod_group,
                        COUNT(*) AS complaint_count,
                        COUNT(DISTINCT complaint_no) AS unique_complaints,
                        0 AS mtd_order_qty,
                        COALESCE(SUM(amt_claim), 0) AS total_claim_amount,
                        COALESCE(SUM(amt_approved), 0) AS total_approved_amount,
                        SUM(CASE WHEN return_flag = 'Y' THEN 1 ELSE 0 END) AS return_count,
                        COALESCE(SUM(CASE WHEN return_flag = 'Y' THEN amt_claim ELSE 0 END), 0) AS return_claim_amount,
                        COALESCE(SUM(CASE WHEN return_flag = 'Y' THEN amt_approved ELSE 0 END), 0) AS return_approved_amount
                    FROM closed_complaints
                    WHERE YEAR(dt_complaint) = :year
                    GROUP BY COALESCE(NULLIF(prod_group, ''), 'Unknown')
                    ORDER BY total_claim_amount DESC, prod_group ASC
                    """
                ),
                {"year": year},
            ).fetchall()

        return ClosedComplaintsSummaryResponse(
            selected_year=year,
            rows=[
                ClosedComplaintsSummaryRow(
                    prod_group=str(row.prod_group),
                    complaint_count=int(row.complaint_count or 0),
                    unique_complaints=int(row.unique_complaints or 0),
                    mtd_order_qty=int(row.mtd_order_qty or 0),
                    total_claim_amount=row.total_claim_amount,
                    total_approved_amount=row.total_approved_amount,
                    return_count=int(row.return_count or 0),
                    return_claim_amount=row.return_claim_amount,
                    return_approved_amount=row.return_approved_amount,
                )
                for row in rows
            ],
        )

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH complaint_summary AS (
                    SELECT
                        COALESCE(NULLIF(prod_group, ''), 'Unknown') AS prod_group,
                        COUNT(*) AS complaint_count,
                        COUNT(DISTINCT complaint_no) AS unique_complaints,
                        COALESCE(SUM(amt_claim), 0) AS total_claim_amount,
                        COALESCE(SUM(amt_approved), 0) AS total_approved_amount,
                        SUM(CASE WHEN return_flag = 'Y' THEN 1 ELSE 0 END) AS return_count,
                        COALESCE(SUM(CASE WHEN return_flag = 'Y' THEN amt_claim ELSE 0 END), 0) AS return_claim_amount,
                        COALESCE(SUM(CASE WHEN return_flag = 'Y' THEN amt_approved ELSE 0 END), 0) AS return_approved_amount
                    FROM closed_complaints
                    WHERE YEAR(dt_complaint) = :year
                    GROUP BY COALESCE(NULLIF(prod_group, ''), 'Unknown')
                ),
                sales_monthly_max AS (
                    SELECT
                        CASE
                            WHEN COALESCE(product_class, '') = :ct_product_class
                             AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :ct_product_name
                                THEN 'CT'
                            WHEN COALESCE(product_class, '') = :bp_product_class
                             AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :bp_product_name
                                THEN 'BP'
                            WHEN COALESCE(product_class, '') = :sw_product_class
                             AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sw_product_name
                                THEN 'SW'
                            WHEN COALESCE(product_class, '') = :is_product_class
                             AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :is_product_name
                                THEN 'IS'
                            WHEN COALESCE(product_class, '') = :sc_product_class
                             AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sc_product_name
                                THEN 'SC'
                            ELSE NULL
                        END AS prod_group,
                        DATE_FORMAT(business_date, '%Y-%m') AS period_key,
                        MAX(mtd_order_qty) AS month_mtd_order_qty
                    FROM sales_summary
                    WHERE YEAR(business_date) = :year
                    GROUP BY prod_group, DATE_FORMAT(business_date, '%Y-%m')
                ),
                sales_summary_totals AS (
                    SELECT
                        prod_group,
                        COALESCE(SUM(month_mtd_order_qty), 0) AS mtd_order_qty
                    FROM sales_monthly_max
                    WHERE prod_group IS NOT NULL
                    GROUP BY prod_group
                )
                SELECT
                    complaint_summary.prod_group,
                    complaint_summary.complaint_count,
                    complaint_summary.unique_complaints,
                    COALESCE(sales_summary_totals.mtd_order_qty, 0) AS mtd_order_qty,
                    complaint_summary.total_claim_amount,
                    complaint_summary.total_approved_amount,
                    complaint_summary.return_count,
                    complaint_summary.return_claim_amount,
                    complaint_summary.return_approved_amount
                FROM complaint_summary
                LEFT JOIN sales_summary_totals
                    ON sales_summary_totals.prod_group = complaint_summary.prod_group
                ORDER BY complaint_summary.total_claim_amount DESC, complaint_summary.prod_group ASC
                """
            ),
            {
                "year": year,
                "ct_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["CT"]["product_class"],
                "ct_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["CT"]["product_name_normalized"],
                "bp_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["BP"]["product_class"],
                "bp_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["BP"]["product_name_normalized"],
                "sw_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SW"]["product_class"],
                "sw_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SW"]["product_name_normalized"],
                "is_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["IS"]["product_class"],
                "is_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["IS"]["product_name_normalized"],
                "sc_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SC"]["product_class"],
                "sc_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SC"]["product_name_normalized"],
            },
        ).fetchall()

    return ClosedComplaintsSummaryResponse(
        selected_year=year,
        rows=[
            ClosedComplaintsSummaryRow(
                prod_group=str(row.prod_group),
                complaint_count=int(row.complaint_count or 0),
                unique_complaints=int(row.unique_complaints or 0),
                mtd_order_qty=int(row.mtd_order_qty or 0),
                total_claim_amount=row.total_claim_amount,
                total_approved_amount=row.total_approved_amount,
                return_count=int(row.return_count or 0),
                return_claim_amount=row.return_claim_amount,
                return_approved_amount=row.return_approved_amount,
            )
            for row in rows
        ],
    )


@router.get(
    "/api/closed-complaints/code-summary",
    response_model=ClosedComplaintsCodeSummaryResponse,
    summary="Closed complaints summary by product group and code",
    description=(
        "Return complaint summary grouped by product group and code using "
        "closed_complaints joined with comp_error_code."
    ),
)
async def closed_complaints_code_summary(
    year: int = Query(..., ge=1900, le=2100, description="Filter summary by complaint year"),
    month: int | None = Query(default=None, ge=1, le=12, description="Optional month filter (1-12)"),
    prod_group: str | None = Query(default=None, description="Optional product group filter"),
    code: str | None = Query(default=None, description="Optional complaint code filter"),
) -> ClosedComplaintsCodeSummaryResponse:
    """Return grouped code summary using closed_complaints joined to comp_error_code."""
    _ensure_closed_complaints_table()

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    COALESCE(NULLIF(cc.prod_group, ''), 'Unknown') AS prod_group,
                    COALESCE(NULLIF(cc.code, ''), 'Unknown') AS code,
                    COALESCE(NULLIF(ce.description, ''), 'Unknown') AS code_description,
                    COUNT(*) AS complaint_count,
                    COALESCE(SUM(cc.amt_claim), 0) AS total_claim_amount,
                    COALESCE(SUM(cc.amt_approved), 0) AS total_approved_amount,
                    SUM(CASE WHEN cc.return_flag = 'Y' THEN 1 ELSE 0 END) AS return_count
                FROM closed_complaints cc
                JOIN comp_error_code ce
                    ON cc.code = ce.code
                WHERE cc.dt_complaint IS NOT NULL
                  AND YEAR(cc.dt_complaint) = :year
                                    AND (:month IS NULL OR MONTH(cc.dt_complaint) = :month)
                                    AND (:prod_group IS NULL OR COALESCE(NULLIF(cc.prod_group, ''), 'Unknown') = :prod_group)
                                    AND (:code IS NULL OR COALESCE(NULLIF(cc.code, ''), 'Unknown') = :code)
                GROUP BY
                    COALESCE(NULLIF(cc.prod_group, ''), 'Unknown'),
                    COALESCE(NULLIF(cc.code, ''), 'Unknown'),
                    COALESCE(NULLIF(ce.description, ''), 'Unknown')
                ORDER BY
                    COALESCE(NULLIF(cc.code, ''), 'Unknown') ASC,
                    COALESCE(NULLIF(cc.prod_group, ''), 'Unknown') ASC
                """
            ),
            {
                "year": year,
                "month": month,
                "prod_group": prod_group,
                "code": code,
            },
        ).fetchall()

    return ClosedComplaintsCodeSummaryResponse(
        selected_year=year,
        rows=[
            ClosedComplaintsCodeSummaryRow(
                prod_group=str(row.prod_group),
                code=str(row.code),
                code_description=str(row.code_description),
                complaint_count=int(row.complaint_count or 0),
                total_claim_amount=row.total_claim_amount,
                total_approved_amount=row.total_approved_amount,
                return_count=int(row.return_count or 0),
            )
            for row in rows
        ],
    )


@router.get(
    "/api/closed-complaints/code-summary/options",
    response_model=ClosedComplaintsCodeSummaryOptionsResponse,
    summary="Closed complaints code summary filter options",
    description=(
        "Return dropdown options for year/month/product group/code used by the "
        "closed complaints grouped code summary table."
    ),
)
async def closed_complaints_code_summary_options(
    year: int | None = Query(default=None, ge=1900, le=2100, description="Optional selected year"),
    month: int | None = Query(default=None, ge=1, le=12, description="Optional selected month"),
    prod_group: str | None = Query(default=None, description="Optional selected product group"),
) -> ClosedComplaintsCodeSummaryOptionsResponse:
    """Return filter option lists for code summary table dropdowns."""
    _ensure_closed_complaints_table()

    with _engine.connect() as conn:
        year_rows = conn.execute(
            text(
                """
                SELECT DISTINCT YEAR(cc.dt_complaint) AS complaint_year
                FROM closed_complaints cc
                JOIN comp_error_code ce ON cc.code = ce.code
                WHERE cc.dt_complaint IS NOT NULL
                ORDER BY complaint_year DESC
                """
            )
        ).fetchall()

        month_rows = conn.execute(
            text(
                """
                SELECT DISTINCT MONTH(cc.dt_complaint) AS complaint_month
                FROM closed_complaints cc
                JOIN comp_error_code ce ON cc.code = ce.code
                WHERE cc.dt_complaint IS NOT NULL
                  AND (:year IS NULL OR YEAR(cc.dt_complaint) = :year)
                ORDER BY complaint_month ASC
                """
            ),
            {"year": year},
        ).fetchall()

        group_rows = conn.execute(
            text(
                """
                SELECT DISTINCT COALESCE(NULLIF(cc.prod_group, ''), 'Unknown') AS prod_group
                FROM closed_complaints cc
                JOIN comp_error_code ce ON cc.code = ce.code
                WHERE cc.dt_complaint IS NOT NULL
                  AND (:year IS NULL OR YEAR(cc.dt_complaint) = :year)
                  AND (:month IS NULL OR MONTH(cc.dt_complaint) = :month)
                ORDER BY prod_group ASC
                """
            ),
            {"year": year, "month": month},
        ).fetchall()

        code_rows = conn.execute(
            text(
                """
                SELECT DISTINCT
                    COALESCE(NULLIF(cc.code, ''), 'Unknown') AS code,
                    COALESCE(NULLIF(ce.description, ''), 'Unknown') AS description
                FROM closed_complaints cc
                JOIN comp_error_code ce ON cc.code = ce.code
                WHERE cc.dt_complaint IS NOT NULL
                  AND (:year IS NULL OR YEAR(cc.dt_complaint) = :year)
                  AND (:month IS NULL OR MONTH(cc.dt_complaint) = :month)
                  AND (:prod_group IS NULL OR COALESCE(NULLIF(cc.prod_group, ''), 'Unknown') = :prod_group)
                ORDER BY code ASC
                """
            ),
            {
                "year": year,
                "month": month,
                "prod_group": prod_group,
            },
        ).fetchall()

    return ClosedComplaintsCodeSummaryOptionsResponse(
        years=[int(row.complaint_year) for row in year_rows if row.complaint_year is not None],
        months=[int(row.complaint_month) for row in month_rows if row.complaint_month is not None],
        prod_groups=[str(row.prod_group) for row in group_rows if row.prod_group is not None],
        codes=[
            ClosedComplaintsCodeOption(code=str(row.code), description=str(row.description))
            for row in code_rows
            if row.code is not None
        ],
    )


@router.get(
    "/api/closed-complaints/trends",
    response_model=ClosedComplaintsTrendResponse,
    summary="Closed complaints daily trends",
    description=(
        "Return daily trend points with Date, MTD_Order_Qty_LBS, Complaints, "
        "Claim_Amount, Approved_Amount, Returns, and Complaint_Rate."
    ),
)
async def closed_complaints_trends(
    year: int = Query(..., ge=1900, le=2100, description="Filter trend data by year"),
) -> ClosedComplaintsTrendResponse:
    """Return daily complaint count and complaint-rate trends split by product group."""
    _ensure_closed_complaints_table()

    if not _sales_summary_table_exists():
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        COALESCE(NULLIF(prod_group, ''), 'Unknown') AS prod_group,
                        dt_complaint AS report_date,
                        0 AS mtd_order_qty_lbs,
                        COUNT(*) AS complaints,
                        COALESCE(SUM(amt_claim), 0) AS claim_amount,
                        COALESCE(SUM(amt_approved), 0) AS approved_amount,
                        SUM(CASE WHEN return_flag = 'Y' THEN 1 ELSE 0 END) AS returns
                    FROM closed_complaints
                    WHERE dt_complaint IS NOT NULL
                      AND YEAR(dt_complaint) = :year
                    GROUP BY COALESCE(NULLIF(prod_group, ''), 'Unknown'), dt_complaint
                    ORDER BY COALESCE(NULLIF(prod_group, ''), 'Unknown') ASC, dt_complaint ASC
                    """
                ),
                {"year": year},
            ).fetchall()
    else:
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    WITH complaint_daily AS (
                        SELECT
                            COALESCE(NULLIF(prod_group, ''), 'Unknown') AS prod_group,
                            dt_complaint AS report_date,
                            COUNT(*) AS complaints,
                            COALESCE(SUM(amt_claim), 0) AS claim_amount,
                            COALESCE(SUM(amt_approved), 0) AS approved_amount,
                            SUM(CASE WHEN return_flag = 'Y' THEN 1 ELSE 0 END) AS returns
                        FROM closed_complaints
                        WHERE dt_complaint IS NOT NULL
                          AND YEAR(dt_complaint) = :year
                        GROUP BY COALESCE(NULLIF(prod_group, ''), 'Unknown'), dt_complaint
                    ),
                    sales_daily AS (
                        SELECT
                            CASE
                                WHEN COALESCE(product_class, '') = :ct_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :ct_product_name
                                    THEN 'CT'
                                WHEN COALESCE(product_class, '') = :bp_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :bp_product_name
                                    THEN 'BP'
                                WHEN COALESCE(product_class, '') = :sw_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sw_product_name
                                    THEN 'SW'
                                WHEN COALESCE(product_class, '') = :is_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :is_product_name
                                    THEN 'IS'
                                WHEN COALESCE(product_class, '') = :sc_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sc_product_name
                                    THEN 'SC'
                                ELSE NULL
                            END AS prod_group,
                            business_date AS report_date,
                            COALESCE(SUM(mtd_order_qty), 0) AS mtd_order_qty_lbs
                        FROM sales_summary
                        WHERE YEAR(business_date) = :year
                          AND (
                                (COALESCE(product_class, '') = :ct_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :ct_product_name)
                             OR (COALESCE(product_class, '') = :bp_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :bp_product_name)
                             OR (COALESCE(product_class, '') = :sw_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sw_product_name)
                             OR (COALESCE(product_class, '') = :is_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :is_product_name)
                             OR (COALESCE(product_class, '') = :sc_product_class
                                 AND REPLACE(REPLACE(UPPER(COALESCE(product_name, '')), ' ', ''), ':', '') = :sc_product_name)
                          )
                        GROUP BY prod_group, business_date
                    ),
                    date_group_series AS (
                        SELECT prod_group, report_date FROM complaint_daily
                        UNION
                        SELECT prod_group, report_date FROM sales_daily
                    )
                    SELECT
                        date_group_series.prod_group,
                        date_group_series.report_date,
                        COALESCE(sales_daily.mtd_order_qty_lbs, 0) AS mtd_order_qty_lbs,
                        COALESCE(complaint_daily.complaints, 0) AS complaints,
                        COALESCE(complaint_daily.claim_amount, 0) AS claim_amount,
                        COALESCE(complaint_daily.approved_amount, 0) AS approved_amount,
                        COALESCE(complaint_daily.returns, 0) AS returns
                    FROM date_group_series
                    LEFT JOIN complaint_daily
                        ON complaint_daily.prod_group = date_group_series.prod_group
                       AND complaint_daily.report_date = date_group_series.report_date
                    LEFT JOIN sales_daily
                        ON sales_daily.prod_group = date_group_series.prod_group
                       AND sales_daily.report_date = date_group_series.report_date
                    ORDER BY date_group_series.prod_group ASC, date_group_series.report_date ASC
                    """
                ),
                {
                    "year": year,
                    "ct_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["CT"]["product_class"],
                    "ct_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["CT"]["product_name_normalized"],
                    "bp_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["BP"]["product_class"],
                    "bp_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["BP"]["product_name_normalized"],
                    "sw_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SW"]["product_class"],
                    "sw_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SW"]["product_name_normalized"],
                    "is_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["IS"]["product_class"],
                    "is_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["IS"]["product_name_normalized"],
                    "sc_product_class": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SC"]["product_class"],
                    "sc_product_name": _PRODUCT_GROUP_SALES_SUMMARY_MAP["SC"]["product_name_normalized"],
                },
            ).fetchall()

    points: list[ClosedComplaintsTrendPoint] = []
    for row in rows:
        mtd_order_qty_lbs = int(row.mtd_order_qty_lbs or 0)
        complaints = int(row.complaints or 0)
        complaint_rate = (complaints / mtd_order_qty_lbs) if mtd_order_qty_lbs else 0.0
        points.append(
            ClosedComplaintsTrendPoint(
                prod_group=str(row.prod_group),
                date=row.report_date.isoformat(),
                mtd_order_qty_lbs=mtd_order_qty_lbs,
                complaints=complaints,
                claim_amount=row.claim_amount,
                approved_amount=row.approved_amount,
                returns=int(row.returns or 0),
                complaint_rate=complaint_rate,
            )
        )

    return ClosedComplaintsTrendResponse(selected_year=year, points=points)


@router.post(
    "/api/closed-complaints/upload",
    response_model=ClosedComplaintsUploadResponse,
    summary="Upload closed complaints Excel file",
    description=(
        "Upload one Excel workbook of closed complaint rows into MySQL. "
        "Duplicate rows are skipped using the complaint, invoice, order, and seq business key."
    ),
)
async def upload_closed_complaints(file: UploadFile = File(...)) -> ClosedComplaintsUploadResponse:
    """Upload and insert closed complaint rows from one Excel file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_name_lower = file.filename.lower()
    if not file_name_lower.endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Only .xls or .xlsx files are allowed.")

    _ensure_closed_complaints_table()

    try:
        content = await file.read()
        if file_name_lower.endswith(".xlsx"):
            parsed_rows = _rows_from_xlsx(content, file.filename)
        else:
            parsed_rows = _rows_from_xls(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Closed complaints upload parse failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to parse uploaded workbook.") from exc

    if not parsed_rows:
        raise HTTPException(status_code=400, detail="No data rows found in uploaded workbook.")

    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT IGNORE INTO closed_complaints (
                    complaint_no, code, invoice_no, seq, order_no, customer,
                    dt_complaint, amt_claim, return_flag, prod_group, description,
                    qty_claim, close_flag, dt_approved, amt_approved, plant, csc,
                    closing_text, sales_rep, prod_type, ccar_cost_center, ship_to,
                    invoice_amt, sort_code, tx_code, confirm_to, source_file, uploaded_at_utc
                ) VALUES (
                    :complaint_no, :code, :invoice_no, :seq, :order_no, :customer,
                    :dt_complaint, :amt_claim, :return_flag, :prod_group, :description,
                    :qty_claim, :close_flag, :dt_approved, :amt_approved, :plant, :csc,
                    :closing_text, :sales_rep, :prod_type, :ccar_cost_center, :ship_to,
                    :invoice_amt, :sort_code, :tx_code, :confirm_to, :source_file, UTC_TIMESTAMP()
                )
                """
            ),
            parsed_rows,
        )

    rows_read = len(parsed_rows)
    rows_inserted = int(result.rowcount or 0)
    duplicate_rows = rows_read - rows_inserted

    logger.info(
        "Closed complaints upload complete for %s: read=%d inserted=%d duplicates=%d",
        file.filename,
        rows_read,
        rows_inserted,
        duplicate_rows,
    )

    return ClosedComplaintsUploadResponse(
        status="ok",
        message=(
            f"Processed {file.filename}. Inserted {rows_inserted} row(s) and skipped "
            f"{duplicate_rows} duplicate row(s)."
        ),
        rows_read=rows_read,
        rows_inserted=rows_inserted,
        duplicate_rows=duplicate_rows,
    )
