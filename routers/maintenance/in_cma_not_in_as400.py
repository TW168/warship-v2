"""PDF upload page for documents labeled In CMA not in AS400."""

from pathlib import PurePosixPath

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.in_cma_not_in_as400 import InCmaNotInAs400UploadResponse

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()


def _ensure_document_table() -> None:
    """Create the PDF document table when it is first needed."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS in_cma_not_in_as400_documents (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size BIGINT UNSIGNED NOT NULL,
                    pdf_data LONGBLOB NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    KEY ix_in_cma_not_in_as400_uploaded_at (uploaded_at_utc)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


@router.get(
    "/in-cma-not-in-as400",
    response_class=HTMLResponse,
    summary="In CMA not in AS400 PDF Upload",
    description="Maintenance page for saving the original In CMA not in AS400 PDF in MySQL.",
)
async def in_cma_not_in_as400_page(request: Request) -> HTMLResponse:
    """Render the PDF upload page."""
    return templates.TemplateResponse(
        request=request,
        name="maintenance/in_cma_not_in_as400.html",
        context={"active_page": "in_cma_not_in_as400"},
    )


@router.post(
    "/api/in-cma-not-in-as400/upload",
    response_model=InCmaNotInAs400UploadResponse,
    summary="Save In CMA not in AS400 PDF",
    description=(
        "Store one uploaded PDF's original bytes, filename, and size in the "
        "in_cma_not_in_as400_documents MySQL table. The PDF is not parsed."
    ),
)
async def upload_in_cma_not_in_as400_pdf(
    file: UploadFile = File(...),
) -> InCmaNotInAs400UploadResponse:
    """Validate and save the original PDF file to MySQL."""
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="A filename is required")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename must be 255 characters or fewer")

    pdf_data = await file.read()
    if not pdf_data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")
    if b"%PDF-" not in pdf_data[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")

    _ensure_document_table()
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO in_cma_not_in_as400_documents
                    (original_filename, file_size, pdf_data)
                VALUES
                    (:original_filename, :file_size, :pdf_data)
                """
            ),
            {
                "original_filename": filename,
                "file_size": len(pdf_data),
                "pdf_data": pdf_data,
            },
        )

    return InCmaNotInAs400UploadResponse(
        id=int(result.lastrowid),
        filename=filename,
        size_bytes=len(pdf_data),
        message="PDF saved to MySQL.",
    )
