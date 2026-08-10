"""SAIA LTL freight load and count exception report ingestion and serving."""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import connect_to_database
from schemas.saia_ltl_freight import SaiaLtlFreightRow, SaiaLtlFreightUploadResponse
from utils.db_serializer import serialize_row
from utils.saia_ltl_parser import parse_saia_ltl_pdf
from logging_config import get_router_logger

router = APIRouter(prefix="/api/shipping/saia-ltl", tags=["Shipping – SAIA LTL Freight"])
logger = get_router_logger("saia_ltl")

_engine = connect_to_database()


@router.post(
    "/upload",
    summary="Upload SAIA LTL freight report",
    description="Multipart PDF upload. Parses the load and count exception report and inserts rows into saia_ltl_freight.",
)
async def upload_saia_ltl(file: UploadFile = File(...)) -> SaiaLtlFreightUploadResponse:
    """Ingest a SAIA LTL freight PDF, parse, and store in the database."""
    try:
        content = await file.read()
        header, detail_rows = parse_saia_ltl_pdf(content, file.filename or "unknown")

        if not header.get("program"):
            logger.warning(f"No program header found in {file.filename}")
            return SaiaLtlFreightUploadResponse(
                filename=file.filename or "unknown",
                rows_inserted=0,
                rows_skipped=0,
                rows_total=0,
                success=False,
            )

        with _engine.connect() as conn:
            inserted = 0
            skipped = 0

            for row_data in detail_rows:
                # Combine header + detail row
                full_row = {
                    "program": header["program"],
                    "report_date": header["report_date"],
                    "report_time": header["report_time"],
                    "pickup_date": header["pickup_date"],
                    "pickup_manifest_number": header["pickup_manifest_number"],
                    "pro_number": row_data["pro_number"],
                    "consignee_name": row_data["consignee_name"],
                    "hunits": row_data["hunits"],
                    "weight": row_data["weight"],
                    "osd_exception": row_data["osd_exception"],
                    "source_file": file.filename,
                }

                try:
                    conn.execute(
                        text(
                            """
                            INSERT INTO saia_ltl_freight
                            (program, report_date, report_time, pickup_date,
                             pickup_manifest_number, pro_number, consignee_name,
                             hunits, weight, osd_exception, source_file)
                            VALUES (:program, :report_date, :report_time, :pickup_date,
                                    :pickup_manifest_number, :pro_number, :consignee_name,
                                    :hunits, :weight, :osd_exception, :source_file)
                            """
                        ),
                        full_row,
                    )
                    inserted += 1
                except Exception as e:
                    logger.debug(f"Skipped PRO {row_data['pro_number']}: {e}")
                    skipped += 1

            conn.commit()

        logger.info(
            f"Uploaded {file.filename}: {inserted} inserted, {skipped} skipped "
            f"({len(detail_rows)} total)"
        )

        return SaiaLtlFreightUploadResponse(
            filename=file.filename or "unknown",
            rows_inserted=inserted,
            rows_skipped=skipped,
            rows_total=len(detail_rows),
            success=True,
        )

    except Exception as e:
        logger.error(f"Upload failed for {file.filename}: {e}")
        return SaiaLtlFreightUploadResponse(
            filename=file.filename or "unknown",
            rows_inserted=0,
            rows_skipped=0,
            rows_total=0,
            success=False,
        )


@router.get(
    "/",
    summary="List SAIA LTL freight records",
    description="Returns paginated saia_ltl_freight rows with optional date and consignee filters.",
)
async def list_saia_ltl(
    skip: int = 0,
    limit: int = 100,
    report_date: str | None = None,
    consignee: str | None = None,
) -> JSONResponse:
    """List freight records with pagination and filters."""
    limit = min(limit, 1000)
    skip = max(skip, 0)

    with _engine.connect() as conn:
        query = "SELECT * FROM saia_ltl_freight WHERE 1=1"
        params = {}

        if report_date:
            query += " AND report_date = :report_date"
            params["report_date"] = report_date

        if consignee:
            query += " AND consignee_name LIKE :consignee"
            params["consignee"] = f"%{consignee}%"

        query += " ORDER BY report_date DESC, pro_number LIMIT :limit OFFSET :skip"
        params["limit"] = limit
        params["skip"] = skip

        rows = conn.execute(text(query), params).mappings().all()

    return JSONResponse(
        content={"data": [serialize_row(r) for r in rows], "count": len(rows)}
    )
