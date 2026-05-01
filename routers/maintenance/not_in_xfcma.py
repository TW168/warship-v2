"""
routers/maintenance/not_in_xfcma.py — "Not in XFCMA" upload and CRUD routes.

Handles the full lifecycle of ``not_in_xfcma`` records:
- Upload one or more QPQUPRFIL PDF reports, parse rows, and bulk-insert.
- Re-uploading the same filename replaces that file's prior rows.
- Full CRUD API (list, create, update, delete) for manual data entry.

PDF parsing
-----------
Two parsers are attempted in sequence for each uploaded file:

1. ``_parse_pdf`` from ``utils.inas400_pdf_parser`` — handles the tabular
   QPQUPRFIL format with defined column positions.
2. ``_parse_not_in_xfcma_text_pdf`` (local fallback) — regex-based line
   parser for text-extracted PDFs that do not have a fixed table layout.

Routes:
    GET    /not-in-xfcma                 — CRUD management page
    GET    /api/not-in-xfcma             — List rows (optional filters)
    POST   /api/not-in-xfcma             — Create one row
    PUT    /api/not-in-xfcma/{row_id}    — Update one row
    DELETE /api/not-in-xfcma/{row_id}    — Delete one row
    POST   /api/not-in-xfcma/upload      — Upload one or more QPQUPRFIL PDFs
"""

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.not_in_xfcma import (
    NotInXfcmaCreateRequest,
    NotInXfcmaDeleteResponse,
    NotInXfcmaRow,
    NotInXfcmaUpdateRequest,
)
from utils.inas400_pdf_parser import _as400_date, _parse_pdf

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# One shared engine for this module (created at import time)
_engine = connect_to_database()

# Regex for the text-layer fallback PDF parser
# Matches one data line: product_code  manu_order  item  pallet  location  rolls  length  weight  [grade]  last_in_date
_XFCMA_LINE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s+"
    r"([\d,]+)\s+([\d,]+)(?:\s+([A-Za-z0-9]{1,5}))?\s+(\d{2}/\d{2}/\d{2})$"
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_model(row) -> NotInXfcmaRow:
    """Map one SQLAlchemy result row to a ``NotInXfcmaRow`` Pydantic model.

    Args:
        row: A SQLAlchemy ``Row`` with columns matching the ``not_in_xfcma`` table.

    Returns:
        A populated ``NotInXfcmaRow`` instance.
    """
    return NotInXfcmaRow(
        id=int(row.id),
        report_datetime=row.report_datetime,
        product_code=row.product_code,
        manu_order=row.manu_order,
        item=int(row.item),
        pallet=row.pallet,
        location=row.location,
        rolls=int(row.rolls),
        length=int(row.length),
        weight=int(row.weight),
        grade=row.grade,
        last_in_date=row.last_in_date,
        created_at_utc=row.created_at_utc,
        source_file=row.source_file,
    )


def _parse_not_in_xfcma_text_pdf(pdf_path: Path) -> list[dict]:
    """Fallback parser for text-line based "Plt In AS400 ... not In XFCMA" PDFs.

    Used when ``utils.inas400_pdf_parser._parse_pdf`` returns no rows
    (e.g., the PDF has a simple text layout rather than a defined table).
    Applies ``_XFCMA_LINE_RE`` to each line of extracted text.

    Args:
        pdf_path: Absolute path to the uploaded PDF.

    Returns:
        List of row dicts with keys matching the ``not_in_xfcma`` column set.
        Returns an empty list when no lines match.
    """
    parsed: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                # Skip known header and summary lines
                if line.startswith(("TOTAL", "COUNT", "Report:")):
                    continue
                if "Plt In As400" in line or "Product Code" in line:
                    continue
                if "Order#" in line or line.startswith("____"):
                    continue

                match = _XFCMA_LINE_RE.match(line)
                if not match:
                    continue

                (
                    product_code, manu_order, item, pallet, location,
                    rolls, length, weight, grade, last_in_date,
                ) = match.groups()

                try:
                    parsed_date = datetime.strptime(last_in_date, "%y/%m/%d").date()
                except ValueError:
                    continue

                parsed.append(
                    {
                        "product_code": product_code,
                        "order":        manu_order,
                        "item":         item,
                        "pallet_no":    pallet,
                        "loc":          location,
                        "rolls":        rolls.replace(",", ""),
                        "length":       length.replace(",", ""),
                        "weight":       weight.replace(",", ""),
                        "grade":        (grade or "")[:5],
                        "last_in_date": parsed_date,
                    }
                )

    return parsed


def _safe_int(raw: str | None) -> int:
    """Parse a numeric string to int, defaulting to 0 on failure.

    Args:
        raw: Raw string value from the parsed PDF row.

    Returns:
        Parsed integer, or 0 when blank or non-numeric.
    """
    s = (raw or "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get(
    "/not-in-xfcma",
    response_class=HTMLResponse,
    summary="Upload Not-in-XFCMA Page",
    description=(
        "Maintenance page for uploading QPQUPRFIL PDF reports and managing "
        "``not_in_xfcma`` records. Supports inline update and delete via HTMX."
    ),
)
async def not_in_xfcma_page(request: Request) -> HTMLResponse:
    """Render the not_in_xfcma upload and management page."""
    return templates.TemplateResponse(
        "maintenance/not_in_xfcma.html",
        {"request": request, "active_page": "not_in_xfcma"},
    )


# ---------------------------------------------------------------------------
# JSON API routes
# ---------------------------------------------------------------------------

@router.get(
    "/api/not-in-xfcma",
    response_model=list[NotInXfcmaRow],
    summary="List Not-in-XFCMA Rows",
    description=(
        "Returns ``not_in_xfcma`` rows ordered by report_datetime desc then id desc. "
        "Optional filters: ``product_code``, ``date_from`` (YYYY-MM-DD), "
        "``date_to`` (YYYY-MM-DD), ``limit`` (default 500, max 5000)."
    ),
)
async def not_in_xfcma_list(
    product_code: Optional[str] = Query(None, description="Filter by product_code"),
    date_from:    Optional[str] = Query(None, description="report_datetime >= YYYY-MM-DD"),
    date_to:      Optional[str] = Query(None, description="report_datetime <= YYYY-MM-DD"),
    limit:        int           = Query(500, ge=1, le=5000),
) -> list[NotInXfcmaRow]:
    """Return not_in_xfcma rows with optional filtering."""
    where_clauses: list[str] = []
    params: dict = {}

    if product_code:
        where_clauses.append("product_code = :product_code")
        params["product_code"] = product_code
    if date_from:
        where_clauses.append("DATE(report_datetime) >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where_clauses.append("DATE(report_datetime) <= :date_to")
        params["date_to"] = date_to

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id, report_datetime, product_code, manu_order, item, pallet,
                    location, rolls, length, weight, grade, last_in_date,
                    created_at_utc, source_file
                FROM not_in_xfcma
                {where}
                ORDER BY report_datetime DESC, id DESC
                LIMIT :limit
                """
            ),
            {**params, "limit": limit},
        ).fetchall()

    return [_row_to_model(r) for r in rows]


@router.post(
    "/api/not-in-xfcma",
    response_model=NotInXfcmaRow,
    summary="Create Not-in-XFCMA Row",
    description="Create a new ``not_in_xfcma`` record and return the inserted row.",
)
async def not_in_xfcma_create(body: NotInXfcmaCreateRequest) -> NotInXfcmaRow:
    """Insert one new not_in_xfcma row and return the created record."""
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO not_in_xfcma
                    (report_datetime, product_code, manu_order, item, pallet,
                     location, rolls, length, weight, grade, last_in_date)
                VALUES
                    (:report_datetime, :product_code, :manu_order, :item, :pallet,
                     :location, :rolls, :length, :weight, :grade, :last_in_date)
                """
            ),
            {
                "report_datetime": body.report_datetime,
                "product_code":   body.product_code,
                "manu_order":     body.manu_order,
                "item":           body.item,
                "pallet":         body.pallet,
                "location":       body.location,
                "rolls":          body.rolls,
                "length":         body.length,
                "weight":         body.weight,
                "grade":          body.grade,
                "last_in_date":   body.last_in_date,
            },
        )
        new_id = result.lastrowid

        row = conn.execute(
            text(
                """
                SELECT id, report_datetime, product_code, manu_order, item, pallet,
                       location, rolls, length, weight, grade, last_in_date,
                       created_at_utc, source_file
                FROM not_in_xfcma WHERE id = :id
                """
            ),
            {"id": new_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=500, detail="Created row could not be retrieved")
    return _row_to_model(row)


@router.put(
    "/api/not-in-xfcma/{row_id}",
    response_model=NotInXfcmaRow,
    summary="Update Not-in-XFCMA Row",
    description="Update an existing ``not_in_xfcma`` record by id.",
)
async def not_in_xfcma_update(row_id: int, body: NotInXfcmaUpdateRequest) -> NotInXfcmaRow:
    """Update one not_in_xfcma row by primary key and return the updated record."""
    updates: list[str] = []
    params: dict = {"id": row_id}

    # Build SET clause from non-None body fields only
    field_map = {
        "report_datetime": body.report_datetime,
        "product_code":    body.product_code,
        "manu_order":      body.manu_order,
        "item":            body.item,
        "pallet":          body.pallet,
        "location":        body.location,
        "rolls":           body.rolls,
        "length":          body.length,
        "weight":          body.weight,
        "grade":           body.grade,
        "last_in_date":    body.last_in_date,
    }
    for col, val in field_map.items():
        if val is not None:
            updates.append(f"{col} = :{col}")
            params[col] = val

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    with _engine.begin() as conn:
        conn.execute(
            text(f"UPDATE not_in_xfcma SET {', '.join(updates)} WHERE id = :id"),
            params,
        )
        row = conn.execute(
            text(
                """
                SELECT id, report_datetime, product_code, manu_order, item, pallet,
                       location, rolls, length, weight, grade, last_in_date,
                       created_at_utc, source_file
                FROM not_in_xfcma WHERE id = :id
                """
            ),
            {"id": row_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Row {row_id} not found")
    return _row_to_model(row)


@router.delete(
    "/api/not-in-xfcma/{row_id}",
    response_model=NotInXfcmaDeleteResponse,
    summary="Delete Not-in-XFCMA Row",
    description="Delete one ``not_in_xfcma`` record by id.",
)
async def not_in_xfcma_delete(row_id: int) -> NotInXfcmaDeleteResponse:
    """Delete one not_in_xfcma row by primary key."""
    with _engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM not_in_xfcma WHERE id = :id"), {"id": row_id}
        )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Row {row_id} not found")

    return NotInXfcmaDeleteResponse(id=row_id, message=f"Row {row_id} deleted successfully")


@router.post(
    "/api/not-in-xfcma/upload",
    summary="Upload Not-in-XFCMA PDF(s)",
    description=(
        "Upload one or more QPQUPRFIL PDF reports. Each file is parsed and its "
        "rows are inserted into ``not_in_xfcma``. Re-uploading the same filename "
        "replaces that file's prior rows (DELETE then INSERT). "
        "Only ``.pdf`` files are accepted."
    ),
)
async def not_in_xfcma_upload_pdf(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Parse uploaded QPQUPRFIL PDFs and upsert rows into not_in_xfcma.

    Raises:
        HTTPException 400: No files provided, non-PDF extension detected,
                           or no parseable data found in any file.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one PDF file")

    all_params: list[dict]  = []
    file_summaries: list[dict] = []
    invalid_files: list[str] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            invalid_files.append(filename or "(unnamed)")
            continue

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(await upload.read())
                temp_path = Path(tmp.name)

            # Try primary parser first, then fallback
            report_dt, parsed_rows = _parse_pdf(temp_path)
            if not parsed_rows:
                parsed_rows = _parse_not_in_xfcma_text_pdf(temp_path)
            if report_dt is None:
                report_dt = datetime.now()

            if not parsed_rows:
                file_summaries.append(
                    {"file": filename, "inserted": 0, "detail": "No rows found"}
                )
                continue

            for row in parsed_rows:
                trans_date = _as400_date(row.get("trans_date", ""))
                if trans_date is None and row.get("last_in_date") is not None:
                    trans_date = row.get("last_in_date")

                all_params.append(
                    {
                        "report_datetime": report_dt,
                        "product_code":   (row.get("product_code") or "").strip(),
                        "manu_order":     (row.get("order") or "").strip(),
                        "item":            _safe_int(row.get("item")),
                        "pallet":         (row.get("pallet_no") or "").strip(),
                        "location":       (row.get("loc") or "").strip(),
                        "rolls":           _safe_int(row.get("rolls")),
                        "length":          _safe_int(row.get("length")),
                        "weight":          _safe_int(row.get("weight")),
                        "grade":          (row.get("grade") or "").strip(),
                        "last_in_date":    trans_date or report_dt.date(),
                        "source_file":     filename,
                    }
                )

            file_summaries.append(
                {
                    "file":            filename,
                    "inserted":        len(parsed_rows),
                    "report_datetime": report_dt.isoformat(sep=" "),
                }
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if invalid_files:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are allowed. Invalid: {', '.join(invalid_files)}",
        )

    if not all_params:
        raise HTTPException(status_code=400, detail="No data rows found in uploaded PDF files")

    # Delete existing rows for each source file so re-upload replaces cleanly
    unique_filenames = list({p["source_file"] for p in all_params})

    with _engine.begin() as conn:
        for fname in unique_filenames:
            conn.execute(
                text("DELETE FROM not_in_xfcma WHERE source_file = :fname"),
                {"fname": fname},
            )

        result = conn.execute(
            text(
                """
                INSERT INTO not_in_xfcma
                    (report_datetime, product_code, manu_order, item, pallet,
                     location, rolls, length, weight, grade, last_in_date,
                     created_at_utc, source_file)
                VALUES
                    (:report_datetime, :product_code, :manu_order, :item, :pallet,
                     :location, :rolls, :length, :weight, :grade, :last_in_date,
                     NOW(), :source_file)
                """
            ),
            all_params,
        )
        inserted_count = int(result.rowcount or 0)

    return JSONResponse(
        content={
            "message":  f"Inserted {inserted_count} rows from {len(file_summaries)} file(s)",
            "inserted": inserted_count,
            "files":    file_summaries,
        }
    )
