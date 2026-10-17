"""Upload and extract the "In CMA not in AS400" PDF report."""

import tempfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.in_cma_not_in_as400 import InCmaNotInAs400UploadResponse
from utils.cma_not_in_as400_parser import parse_in_cma_not_in_as400_pdf

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS in_cma_not_in_as400 (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        report_datetime DATETIME NOT NULL,
        original_in_date DATE NOT NULL,
        last_date DATE NOT NULL,
        order_no VARCHAR(40) NULL,
        product_code VARCHAR(100) NULL,
        sw_plt_no VARCHAR(40) NULL,
        machine_no VARCHAR(20) NULL,
        cell_id VARCHAR(20) NULL,
        site VARCHAR(40) NULL,
        location VARCHAR(80) NULL,
        grade VARCHAR(30) NULL,
        as400_order_no VARCHAR(40) NULL,
        item_id VARCHAR(40) NULL,
        weight VARCHAR(40) NULL,
        wip VARCHAR(40) NULL,
        repack_plt_no VARCHAR(40) NULL,
        change_date VARCHAR(40) NULL,
        remark TEXT NULL,
        source_file VARCHAR(255) NOT NULL,
        uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
        KEY ix_in_cma_not_in_as400_report_datetime (report_datetime),
        KEY ix_in_cma_not_in_as400_source_file (source_file)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_INSERT_ROW_SQL = """
    INSERT INTO in_cma_not_in_as400 (
        report_datetime, original_in_date, last_date, order_no, product_code,
        sw_plt_no, machine_no, cell_id, site, location, grade, as400_order_no,
        item_id, weight, wip, repack_plt_no, change_date, remark, source_file
    ) VALUES (
        :report_datetime, :original_in_date, :last_date, :order_no, :product_code,
        :sw_plt_no, :machine_no, :cell_id, :site, :location, :grade,
        :as400_order_no, :item_id, :weight, :wip, :repack_plt_no, :change_date,
        :remark, :source_file
    )
"""


@router.get(
    "/in-cma-not-in-as400",
    response_class=HTMLResponse,
    summary="In CMA not in AS400 Report Upload",
    description="Maintenance page for extracting report rows from the CMA/AS400 PDF into MySQL.",
)
async def in_cma_not_in_as400_page(request: Request) -> HTMLResponse:
    """Render the report upload page."""
    return templates.TemplateResponse(
        request=request,
        name="maintenance/in_cma_not_in_as400.html",
        context={"active_page": "in_cma_not_in_as400"},
    )


@router.post(
    "/api/in-cma-not-in-as400/upload",
    response_model=InCmaNotInAs400UploadResponse,
    summary="Extract and Save In CMA not in AS400 PDF",
    description=(
        "Extract the fixed-width QPQUPRFIL report rows and save the structured "
        "values in the in_cma_not_in_as400 MySQL table. Re-uploading a filename "
        "replaces rows previously imported from that filename."
    ),
)
async def upload_in_cma_not_in_as400_pdf(
    file: UploadFile = File(...),
) -> InCmaNotInAs400UploadResponse:
    """Extract report rows from the uploaded PDF and replace that file's database rows."""
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="A filename is required")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename must be 255 characters or fewer")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")
    if b"%PDF-" not in contents[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(contents)
            temp_path = Path(temp_file.name)

        report_datetime, parsed_rows = parse_in_cma_not_in_as400_pdf(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if report_datetime is None:
        raise HTTPException(status_code=400, detail="The PDF report timestamp was not found")
    if not parsed_rows:
        raise HTTPException(
            status_code=400,
            detail="No report rows were extracted; no database rows were changed",
        )

    insert_rows = [
        {
            **row,
            "report_datetime": report_datetime,
            "source_file": filename,
        }
        for row in parsed_rows
    ]

    with _engine.begin() as conn:
        conn.execute(text(_CREATE_TABLE_SQL))
        conn.execute(
            text("DELETE FROM in_cma_not_in_as400 WHERE source_file = :source_file"),
            {"source_file": filename},
        )
        conn.execute(text(_INSERT_ROW_SQL), insert_rows)

    row_label = "row" if len(insert_rows) == 1 else "rows"
    return InCmaNotInAs400UploadResponse(
        filename=filename,
        report_datetime=report_datetime,
        parsed_rows=len(parsed_rows),
        inserted_rows=len(insert_rows),
        message=f"Extracted and saved {len(insert_rows)} report {row_label} to MySQL.",
    )
