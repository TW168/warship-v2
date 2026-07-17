"""Production work-order XLSX upload routes with normalized JSON conversion."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.work_order_upload import (
    WorkOrderBridgedMaterialTotalRow,
    WorkOrderDailyUsageDetailRow,
    WorkOrderDailyUsageLineSiloRow,
    WorkOrderDailyUsageMaterialTotalRow,
    WorkOrderDailyUsageResponse,
    WorkOrderHopperMaterialBridgeRow,
    WorkOrderDailyUsageRow,
    WorkOrderExtractedRow,
    WorkOrderFileSummary,
    WorkOrderSheetSummary,
    WorkOrderUploadResponse,
)
from utils.work_order_json_parser import parse_work_order_workbook_bytes

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

_LINE_RE = re.compile(r"^[A-Za-z0-9]{4}")
_UPLOAD_TRACKING_TABLE = "extruction_prod_ticket_uploads"



def _extract_line_from_filename(filename: str) -> str:
    """Read production line from first 4 filename characters."""
    match = _LINE_RE.match(filename)
    if not match:
        raise ValueError("Filename must start with at least 4 alphanumeric characters for production line.")
    return match.group(0).upper()


def _line_table_name(production_line: str) -> str:
    """Build one physical table name per production line."""
    return f"extrusion_prod_ticket_{production_line.lower()}"


def _ensure_upload_tracking_table() -> None:
    """Create upload tracking table for duplicate prevention and audit."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {_UPLOAD_TRACKING_TABLE} (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    source_file VARCHAR(255) NOT NULL,
                    source_file_size BIGINT NOT NULL,
                    source_file_hash CHAR(64) NULL,
                    production_line CHAR(4) NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    sheet_count INT NOT NULL DEFAULT 0,
                    inserted_rows INT NOT NULL DEFAULT 0,
                    UNIQUE KEY ux_work_order_upload_hash (source_file, source_file_hash)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

        existing_columns = {
            row[0]
            for row in conn.execute(text(f"SHOW COLUMNS FROM {_UPLOAD_TRACKING_TABLE}")).fetchall()
        }
        if "source_file_hash" not in existing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE {_UPLOAD_TRACKING_TABLE} "
                    "ADD COLUMN source_file_hash CHAR(64) NULL AFTER source_file_size"
                )
            )

        existing_indexes = {
            row[2]
            for row in conn.execute(text(f"SHOW INDEX FROM {_UPLOAD_TRACKING_TABLE}")).fetchall()
        }
        if "ux_work_order_upload" in existing_indexes:
            conn.execute(text(f"ALTER TABLE {_UPLOAD_TRACKING_TABLE} DROP INDEX ux_work_order_upload"))
            existing_indexes.remove("ux_work_order_upload")
        if "ux_work_order_upload_hash" not in existing_indexes:
            conn.execute(
                text(
                    f"ALTER TABLE {_UPLOAD_TRACKING_TABLE} "
                    "ADD UNIQUE INDEX ux_work_order_upload_hash (source_file, source_file_hash)"
                )
            )


def _ensure_line_table(table_name: str) -> None:
    """Create or migrate a per-line table that stores one JSON document per sheet."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    upload_id BIGINT NOT NULL,
                    source_file VARCHAR(255) NOT NULL,
                    source_file_size BIGINT NOT NULL,
                    source_file_hash CHAR(64) NULL,
                    production_line CHAR(4) NOT NULL,
                    sheet_name VARCHAR(128) NOT NULL,
                    sheet_index INT NOT NULL,
                    document_hash CHAR(64) NOT NULL,
                    document_payload JSON NOT NULL,
                    document_payload_raw LONGTEXT NULL,
                    created_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    UNIQUE KEY ux_work_order_sheet_hash (source_file, source_file_hash, sheet_name),
                    KEY ix_work_order_created (created_at_utc),
                    CONSTRAINT fk_{table_name}_upload
                        FOREIGN KEY (upload_id) REFERENCES {_UPLOAD_TRACKING_TABLE}(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

        existing_columns = {
            row[0]
            for row in conn.execute(text(f"SHOW COLUMNS FROM {table_name}")).fetchall()
        }

        if "document_hash" not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN document_hash CHAR(64) NULL"))
        if "document_payload" not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN document_payload JSON NULL"))
        if "document_payload_raw" not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN document_payload_raw LONGTEXT NULL"))
        if "source_file_hash" not in existing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN source_file_hash CHAR(64) NULL AFTER source_file_size"
                )
            )

        existing_indexes = {
            row[2]
            for row in conn.execute(text(f"SHOW INDEX FROM {table_name}")).fetchall()
        }
        if "ux_work_order_sheet" in existing_indexes:
            conn.execute(text(f"ALTER TABLE {table_name} DROP INDEX ux_work_order_sheet"))
            existing_indexes.remove("ux_work_order_sheet")
        if "ux_work_order_sheet_hash" not in existing_indexes:
            conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD UNIQUE INDEX ux_work_order_sheet_hash (source_file, source_file_hash, sheet_name)"
                )
            )


def _sheet_summary_from_document(
    sheet_name: str,
    sheet_index: int,
    document: dict[str, Any] | None,
    skipped: bool,
    skip_reason: str | None,
) -> WorkOrderSheetSummary:
    """Build compact per-sheet preview for API/UI response."""
    metadata_preview: dict[str, str] = {}
    charting_preview: dict[str, Any] = {}

    if document:
        ticket = document.get("ticket", {}) if isinstance(document, dict) else {}
        metadata_preview = {
            "line": str(ticket.get("line", document.get("metadata", {}).get("line", ""))),
            "date": str(ticket.get("prod_date", document.get("metadata", {}).get("date", ""))),
            "ewo": str(ticket.get("ewo", document.get("metadata", {}).get("ewo", ""))),
            "shift": str(ticket.get("shift", document.get("metadata", {}).get("shift", ""))),
            "crew": str(ticket.get("crew", document.get("metadata", {}).get("crew", ""))),
            "operator": str(ticket.get("operator", document.get("metadata", {}).get("operator", ""))),
        }
        charting_list = ticket.get("charting") if isinstance(ticket.get("charting"), list) else None
        charting = charting_list[0] if charting_list else document.get("charting", {})
        charting_preview = {
            "chart": charting.get("chart", ""),
            "film_type": charting.get("film_type", ""),
            "prod_wgt_lbs": charting.get("prod_weight_lbs", charting.get("prod_wgt_lbs", None)),
            "yield_pct": charting.get("yield", charting.get("yield_pct", 0)),
            "ticket_id": "_".join(
                part
                for part in [
                    metadata_preview.get("line", ""),
                    metadata_preview.get("date", ""),
                    metadata_preview.get("ewo", ""),
                ]
                if part
            ),
        }

    return WorkOrderSheetSummary(
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        inserted_rows=0 if skipped else 1,
        skipped=skipped,
        skip_reason=skip_reason,
        metadata_preview=metadata_preview,
        charting_preview=charting_preview,
    )


def _fetch_extracted_rows_preview(
    table_name: str,
    source_file: str,
    source_file_size: int,
    source_file_hash: str | None = None,
    limit: int = 20,
) -> list[WorkOrderExtractedRow]:
    """Fetch stored parsed documents for preview."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id,
                    upload_id,
                    source_file,
                    source_file_size,
                    production_line,
                    sheet_name,
                    sheet_index,
                    COALESCE(document_hash, '') AS document_hash,
                    document_payload,
                                        document_payload_raw,
                    created_at_utc
                FROM {table_name}
                WHERE source_file = :source_file
                                    AND (
                                        (:source_file_hash IS NOT NULL AND source_file_hash = :source_file_hash)
                                        OR (:source_file_hash IS NULL AND source_file_size = :source_file_size)
                                    )
                ORDER BY sheet_index ASC
                LIMIT :limit
                """
            ),
            {
                "source_file": source_file,
                "source_file_size": source_file_size,
                                "source_file_hash": source_file_hash,
                "limit": limit,
            },
        ).fetchall()

    output: list[WorkOrderExtractedRow] = []
    for row in rows:
        payload_value = row.document_payload_raw
        if not (isinstance(payload_value, str) and payload_value.strip()):
            payload_value = row.document_payload
            if isinstance(payload_value, str):
                try:
                    payload_value = json.loads(payload_value)
                except ValueError:
                    pass

        output.append(
            WorkOrderExtractedRow(
                id=int(row.id),
                upload_id=int(row.upload_id),
                source_file=str(row.source_file),
                source_file_size=int(row.source_file_size),
                production_line=str(row.production_line),
                sheet_name=str(row.sheet_name),
                sheet_index=int(row.sheet_index),
                document_hash=str(row.document_hash),
                document_payload=payload_value,
                created_at_utc=row.created_at_utc,
            )
        )

    return output


def _preview_rows_from_parsed_documents(
    parsed_documents: list[dict[str, Any]],
    source_file: str,
    source_file_size: int,
    production_line: str,
) -> list[WorkOrderExtractedRow]:
    """Build preview rows from freshly parsed documents without reading stored JSON back."""
    preview_rows: list[WorkOrderExtractedRow] = []

    for index, parsed in enumerate(parsed_documents, start=1):
        document_payload = parsed["document"]
        document_hash = hashlib.sha256(
            json.dumps(document_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        preview_rows.append(
            WorkOrderExtractedRow(
                id=index,
                upload_id=0,
                source_file=source_file,
                source_file_size=source_file_size,
                production_line=production_line,
                sheet_name=str(parsed["sheet_name"]),
                sheet_index=int(parsed["sheet_index"]),
                document_hash=document_hash,
                document_payload=document_payload,
                created_at_utc=datetime.utcnow(),
            )
        )

    return preview_rows


def _document_work_date(document: dict[str, Any] | None) -> str | None:
    """Return work date from either the new ticket schema or the legacy schema."""
    if not isinstance(document, dict):
        return None
    ticket = document.get("ticket")
    if isinstance(ticket, dict):
        value = ticket.get("prod_date")
        if value:
            return str(value)
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("date")
        if value:
            return str(value)
    return None


def _document_charting(document: dict[str, Any] | None) -> dict[str, Any]:
    """Return the first charting block from the new schema or legacy charting dict."""
    if not isinstance(document, dict):
        return {}
    ticket = document.get("ticket")
    if isinstance(ticket, dict):
        charting = ticket.get("charting")
        if isinstance(charting, list) and charting:
            first = charting[0]
            if isinstance(first, dict):
                return first
    legacy = document.get("charting")
    return legacy if isinstance(legacy, dict) else {}


def _document_material_usage_rows(document: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten material usage rows from new nested sections or legacy flat array."""
    if not isinstance(document, dict):
        return []
    ticket = document.get("ticket")
    if isinstance(ticket, dict):
        material_usage = ticket.get("material_usage")
        if isinstance(material_usage, dict):
            rows: list[dict[str, Any]] = []
            for key in ["extruder", "ext_b", "ext_c", "ext_d"]:
                block = material_usage.get(key)
                if isinstance(block, list):
                    rows.extend(item for item in block if isinstance(item, dict))
            return rows
    legacy = document.get("material_usage")
    return [item for item in legacy if isinstance(item, dict)] if isinstance(legacy, list) else []


def _derive_material_code(
    usage_row: dict[str, Any],
    formula_code: str,
    film_type_code: str,
) -> str:
    """Resolve one material code from parsed usage row with fallback guards."""
    silo = str((usage_row or {}).get("silo") or "").strip()
    hopper = str((usage_row or {}).get("hopper") or "").strip()
    silo_key = silo.upper()
    hopper_key = hopper.upper()
    invalid_silo_values = {"UNKNOWN", "N/A", "NA", "-", ""}

    silo_looks_like_formula = bool(formula_code and silo_key == formula_code)
    silo_looks_like_film_type = bool(film_type_code and silo_key == film_type_code)
    hopper_looks_like_formula = bool(formula_code and hopper_key == formula_code)
    hopper_looks_like_film_type = bool(film_type_code and hopper_key == film_type_code)

    if silo_key not in invalid_silo_values and not silo_looks_like_formula and not silo_looks_like_film_type:
        return silo or "UNKNOWN"
    if hopper and not hopper_looks_like_formula and not hopper_looks_like_film_type:
        return hopper
    return "UNKNOWN"


@router.get(
    "/api/work-order-upload/daily-usage-history",
    summary="Daily work-order usage history",
    description=(
        "Return day-level production usage totals from stored work-order payloads "
        "for the selected lookback window. Used by the Silos Status Daily Loss Check chart."
    ),
)
async def daily_work_order_usage_history(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    material_code: str | None = Query(
        None,
        description="Optional material/product filter aligned to silo contents code",
    ),
) -> JSONResponse:
    """Aggregate one total production-used lbs value per work date."""
    cutoff_date = datetime.utcnow().date() - timedelta(days=days)
    normalized_material = (material_code or "").strip().upper()
    material_codes: set[str] = set()

    with _engine.connect() as conn:
        tables = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name LIKE 'extrusion_prod_ticket_%'
                ORDER BY table_name
                """
            )
        ).fetchall()

        totals_by_date: dict[str, float] = {}

        for (table_name,) in tables:
            rows = conn.execute(
                text(
                    f"""
                    SELECT document_payload_raw, document_payload
                    FROM {table_name}
                    WHERE STR_TO_DATE(
                        COALESCE(
                            CASE
                                WHEN JSON_VALID(document_payload_raw)
                                THEN JSON_UNQUOTE(JSON_EXTRACT(document_payload_raw, '$.ticket.prod_date'))
                                ELSE NULL
                            END,
                            CASE
                                WHEN JSON_VALID(document_payload_raw)
                                THEN JSON_UNQUOTE(JSON_EXTRACT(document_payload_raw, '$.metadata.date'))
                                ELSE NULL
                            END,
                            JSON_UNQUOTE(JSON_EXTRACT(document_payload, '$.ticket.prod_date')),
                            JSON_UNQUOTE(JSON_EXTRACT(document_payload, '$.metadata.date'))
                        ),
                        '%Y-%m-%d'
                    ) >= :cutoff_date
                    """
                ),
                {"cutoff_date": cutoff_date},
            ).mappings().all()

            for row in rows:
                payload: dict[str, Any] | None = None
                payload_raw = row.get("document_payload_raw")

                # Prefer raw payload so the chart uses the exact stored source document.
                if isinstance(payload_raw, str) and payload_raw.strip():
                    try:
                        parsed_raw = json.loads(payload_raw)
                    except ValueError:
                        parsed_raw = None
                    if isinstance(parsed_raw, dict):
                        payload = parsed_raw

                if payload is None:
                    payload_candidate = row.get("document_payload")
                    if isinstance(payload_candidate, str):
                        try:
                            payload_candidate = json.loads(payload_candidate)
                        except ValueError:
                            payload_candidate = None
                    if isinstance(payload_candidate, dict):
                        payload = payload_candidate

                if not isinstance(payload, dict):
                    continue

                work_date = _document_work_date(payload)
                if not work_date:
                    continue
                try:
                    parsed_work_date = datetime.strptime(work_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if parsed_work_date < cutoff_date:
                    continue

                charting = _document_charting(payload)
                formula_code = str(charting.get("formula") or "").strip().upper()
                film_type = str(charting.get("film_type") or "").strip()
                film_type_code = film_type.upper() if film_type else ""

                day_total = 0.0
                for usage in _document_material_usage_rows(payload):
                    hopper = str((usage or {}).get("hopper") or "").strip()
                    if not hopper:
                        continue

                    usage_material = _derive_material_code(
                        usage_row=usage,
                        formula_code=formula_code,
                        film_type_code=film_type_code,
                    )
                    if usage_material and usage_material.strip().upper() != "UNKNOWN":
                        material_codes.add(usage_material.strip().upper())
                    if normalized_material and usage_material.strip().upper() != normalized_material:
                        continue

                    try:
                        input_lbs = float((usage or {}).get("input_lbs") or 0)
                    except (TypeError, ValueError):
                        input_lbs = 0.0
                    day_total += input_lbs

                totals_by_date[work_date] = float(totals_by_date.get(work_date, 0.0)) + day_total

    history = [
        {
            "work_date": work_date,
            "total_input_lbs": round(total_input_lbs, 3),
        }
        for work_date, total_input_lbs in sorted(totals_by_date.items(), key=lambda item: item[0])
    ]
    return JSONResponse(content={"data": history, "material_codes": sorted(material_codes)})


@router.get(
    "/api/work-order-upload/daily-usage",
    response_model=WorkOrderDailyUsageResponse,
    summary="Daily work-order hopper usage",
    description=(
        "Return hopper-level usage grouped by work date across all stored "
        "production lines. This is used by the Silos Status reconciliation view "
        "to compare CFP hopper totals with actual silo product totals."
    ),
)
async def daily_work_order_usage(work_date: str) -> WorkOrderDailyUsageResponse:
    """Aggregate stored work-order material usage rows for one date."""
    with _engine.connect() as conn:
        tables = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name LIKE 'extrusion_prod_ticket_%'
                ORDER BY table_name
                """
            )
        ).fetchall()

        hopper_aggregates: dict[str, dict[str, object]] = {}
        hopper_material_aggregates: dict[str, dict[str, float]] = {}
        material_aggregates: dict[str, dict[str, object]] = {}
        line_silo_aggregates: dict[str, dict[str, object]] = {}
        detail_rows: list[WorkOrderDailyUsageDetailRow] = []
        total_input_lbs = 0.0

        for (table_name,) in tables:
            rows = conn.execute(
                text(
                    f"""
                    SELECT production_line, sheet_name, document_payload
                    FROM {table_name}
                    WHERE COALESCE(
                        JSON_UNQUOTE(JSON_EXTRACT(document_payload, '$.ticket.prod_date')),
                        JSON_UNQUOTE(JSON_EXTRACT(document_payload, '$.metadata.date'))
                    ) = :work_date
                    """
                ),
                {"work_date": work_date},
            ).mappings().all()

            for row in rows:
                payload = row["document_payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        payload = None

                usage_rows = _document_material_usage_rows(payload if isinstance(payload, dict) else None)
                charting = _document_charting(payload if isinstance(payload, dict) else None)
                formula_code = str(charting.get("formula") or "").strip().upper()
                film_type = str(charting.get("film_type") or "").strip() or None
                film_type_code = (film_type or "").strip().upper()
                production_line = str(row.get("production_line") or "UNKNOWN").strip() or "UNKNOWN"
                sheet_name = str(row.get("sheet_name") or "").strip()

                for usage in usage_rows:
                    hopper = str((usage or {}).get("hopper") or "").strip()
                    if not hopper:
                        continue

                    input_lbs = float((usage or {}).get("input_lbs") or 0)
                    silo = str((usage or {}).get("silo") or "").strip() or "UNKNOWN"
                    material_code = _derive_material_code(
                        usage_row=usage,
                        formula_code=formula_code,
                        film_type_code=film_type_code,
                    )
                    std_percentage = (usage or {}).get("std_pct")
                    if std_percentage is None:
                        std_percentage = (usage or {}).get("std")
                    if std_percentage is None:
                        std_percentage = (usage or {}).get("std_percentage")
                    if std_percentage is not None:
                        try:
                            std_percentage = float(std_percentage)
                        except (TypeError, ValueError):
                            std_percentage = None

                    total_input_lbs += input_lbs
                    detail_rows.append(
                        WorkOrderDailyUsageDetailRow(
                            production_line=production_line,
                            sheet_name=sheet_name,
                            material_code=material_code,
                            film_type=film_type,
                            silo=silo,
                            hopper=hopper,
                            std_percentage=std_percentage,
                            input_lbs=input_lbs,
                        )
                    )

                    hopper_key = hopper
                    hopper_current = hopper_aggregates.get(hopper_key) or {
                        "production_line": "ALL",
                        "work_date": work_date,
                        "hopper": hopper,
                        "total_input_lbs": 0.0,
                        "total_sheets": 0,
                    }
                    hopper_current["total_input_lbs"] = float(hopper_current["total_input_lbs"]) + input_lbs
                    hopper_current["total_sheets"] = int(hopper_current["total_sheets"]) + 1
                    hopper_aggregates[hopper_key] = hopper_current

                    hopper_material_current = hopper_material_aggregates.get(hopper_key) or {}
                    material_for_hopper = material_code or "UNKNOWN"
                    hopper_material_current[material_for_hopper] = float(
                        hopper_material_current.get(material_for_hopper, 0.0)
                    ) + input_lbs
                    hopper_material_aggregates[hopper_key] = hopper_material_current

                    material_key = material_code
                    material_current = material_aggregates.get(material_key) or {
                        "material_code": material_code,
                        "total_input_lbs": 0.0,
                        "row_count": 0,
                    }
                    material_current["total_input_lbs"] = float(material_current["total_input_lbs"]) + input_lbs
                    material_current["row_count"] = int(material_current["row_count"]) + 1
                    material_aggregates[material_key] = material_current

                    line_silo_key = f"{production_line}::{silo}"
                    line_silo_current = line_silo_aggregates.get(line_silo_key) or {
                        "production_line": production_line,
                        "silo": silo,
                        "total_input_lbs": 0.0,
                        "row_count": 0,
                    }
                    line_silo_current["total_input_lbs"] = float(line_silo_current["total_input_lbs"]) + input_lbs
                    line_silo_current["row_count"] = int(line_silo_current["row_count"]) + 1
                    line_silo_aggregates[line_silo_key] = line_silo_current

    rows = [
        WorkOrderDailyUsageRow(**item)
        for item in sorted(hopper_aggregates.values(), key=lambda item: str(item["hopper"]))
    ]
    material_totals = [
        WorkOrderDailyUsageMaterialTotalRow(**item)
        for item in sorted(material_aggregates.values(), key=lambda item: str(item["material_code"]))
    ]
    line_silo_totals = [
        WorkOrderDailyUsageLineSiloRow(**item)
        for item in sorted(
            line_silo_aggregates.values(),
            key=lambda item: (str(item["production_line"]), str(item["silo"])),
        )
    ]

    hopper_material_bridge_rows: list[WorkOrderHopperMaterialBridgeRow] = []
    bridged_material_aggregates: dict[str, dict[str, float | int]] = {}
    for hopper_name, material_map in sorted(hopper_material_aggregates.items(), key=lambda item: item[0]):
        total_lbs = float(sum(material_map.values()))
        if total_lbs <= 0:
            continue

        mapped_material_code, mapped_input_lbs = max(material_map.items(), key=lambda item: item[1])
        mapping_share_pct = (float(mapped_input_lbs) / total_lbs) * 100.0
        distinct_materials = len(material_map)
        if mapping_share_pct >= 90:
            confidence = "high"
        elif mapping_share_pct >= 60:
            confidence = "medium"
        else:
            confidence = "low"

        hopper_material_bridge_rows.append(
            WorkOrderHopperMaterialBridgeRow(
                hopper=hopper_name,
                mapped_material_code=mapped_material_code,
                total_input_lbs=total_lbs,
                mapped_input_lbs=float(mapped_input_lbs),
                mapping_share_pct=mapping_share_pct,
                distinct_materials=distinct_materials,
                confidence=confidence,
            )
        )

        bridged_current = bridged_material_aggregates.get(mapped_material_code) or {
            "total_input_lbs": 0.0,
            "hopper_count": 0,
            "weighted_share_numerator": 0.0,
        }
        bridged_current["total_input_lbs"] = float(bridged_current["total_input_lbs"]) + total_lbs
        bridged_current["hopper_count"] = int(bridged_current["hopper_count"]) + 1
        bridged_current["weighted_share_numerator"] = float(bridged_current["weighted_share_numerator"]) + (
            total_lbs * mapping_share_pct
        )
        bridged_material_aggregates[mapped_material_code] = bridged_current

    bridged_material_totals: list[WorkOrderBridgedMaterialTotalRow] = []
    for material_code, aggregate in sorted(bridged_material_aggregates.items(), key=lambda item: item[0]):
        total_lbs = float(aggregate["total_input_lbs"])
        weighted_share_pct = (
            float(aggregate["weighted_share_numerator"]) / total_lbs
            if total_lbs > 0
            else 0.0
        )
        bridged_material_totals.append(
            WorkOrderBridgedMaterialTotalRow(
                material_code=material_code,
                total_input_lbs=total_lbs,
                hopper_count=int(aggregate["hopper_count"]),
                weighted_share_pct=weighted_share_pct,
            )
        )
    detail_rows.sort(
        key=lambda item: (
            item.production_line,
            item.silo or "",
            item.hopper,
            item.material_code,
            item.sheet_name,
        )
    )

    return WorkOrderDailyUsageResponse(
        work_date=work_date,
        total_input_lbs=total_input_lbs,
        rows=rows,
        details=detail_rows,
        material_totals=material_totals,
        line_silo_totals=line_silo_totals,
        hopper_material_bridge=hopper_material_bridge_rows,
        bridged_material_totals=bridged_material_totals,
    )


@router.get(
    "/work-order-upload",
    response_class=HTMLResponse,
    summary="Production line work-order upload page",
    description="Maintenance page for uploading multi-sheet production work-order XLSX files.",
)
async def work_order_upload_page(request: Request) -> HTMLResponse:
    """Render the work-order XLSX upload page."""
    return templates.TemplateResponse(
        "maintenance/work_order_upload.html",
        {"request": request, "active_page": "work_order_upload"},
    )


@router.post(
    "/api/work-order-upload",
    response_model=WorkOrderUploadResponse,
    summary="Upload production work-order XLSX",
    description=(
        "Upload one or more production line work-order XLSX files. "
        "Production line is read from the first 4 filename characters. "
        "Sheets starting with 'Timeline' are skipped and all other sheets are "
        "converted to the standardized JSON schema."
    ),
)
async def upload_work_order_files(files: list[UploadFile] = File(...)) -> WorkOrderUploadResponse:
    """Parse and persist one normalized JSON document per non-timeline worksheet."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one XLSX file.")

    _ensure_upload_tracking_table()

    file_summaries: list[WorkOrderFileSummary] = []
    total_inserted = 0
    total_skipped = 0

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename:
            raise HTTPException(status_code=400, detail="Uploaded file is missing a filename.")
        if not filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=422, detail=f"Only .xlsx is supported: {filename}")

        try:
            production_line = _extract_line_from_filename(filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{filename}: {exc}") from exc

        content = await upload.read()
        file_size = len(content)
        file_hash = hashlib.sha256(content).hexdigest()
        if file_size <= 0:
            raise HTTPException(status_code=422, detail=f"{filename}: file is empty.")

        line_table = _line_table_name(production_line)
        _ensure_line_table(line_table)

        with _engine.connect() as conn:
            duplicate = conn.execute(
                text(
                    f"""
                    SELECT id
                    FROM {_UPLOAD_TRACKING_TABLE}
                    WHERE source_file = :source_file AND source_file_hash = :source_file_hash
                    LIMIT 1
                    """
                ),
                {"source_file": filename, "source_file_hash": file_hash},
            ).fetchone()

        parsed_documents, skipped_documents = parse_work_order_workbook_bytes(content)
        sheet_count = len(parsed_documents) + len(skipped_documents)

        # Build summaries from uploaded workbook (including skipped Timeline sheets).
        sheet_summaries: list[WorkOrderSheetSummary] = []

        for parsed in parsed_documents:
            sheet_summaries.append(
                _sheet_summary_from_document(
                    sheet_name=str(parsed["sheet_name"]),
                    sheet_index=int(parsed["sheet_index"]),
                    document=parsed["document"],
                    skipped=False,
                    skip_reason=None,
                )
            )

        for skipped in skipped_documents:
            sheet_summaries.append(
                _sheet_summary_from_document(
                    sheet_name=str(skipped["sheet_name"]),
                    sheet_index=int(skipped["sheet_index"]),
                    document=None,
                    skipped=True,
                    skip_reason=str(skipped["reason"]),
                )
            )

        sheet_summaries.sort(key=lambda item: item.sheet_index)

        skipped_sheets = sum(1 for s in sheet_summaries if s.skipped)
        parsed_sheets = len(parsed_documents)

        if duplicate is not None:
            extracted_rows = _preview_rows_from_parsed_documents(
                parsed_documents=parsed_documents,
                source_file=filename,
                source_file_size=file_size,
                production_line=production_line,
            )

            total_skipped += skipped_sheets
            file_summaries.append(
                WorkOrderFileSummary(
                    file_name=filename,
                    production_line=production_line,
                    target_table=line_table,
                    inserted_rows=0,
                    skipped_rows=skipped_sheets,
                    parsed_sheets=parsed_sheets,
                    skipped_sheets=skipped_sheets,
                    sheets=sheet_summaries,
                    extracted_rows=extracted_rows,
                )
            )
            continue

        with _engine.begin() as conn:
            upload_result = conn.execute(
                text(
                    f"""
                    INSERT INTO {_UPLOAD_TRACKING_TABLE}
                        (source_file, source_file_size, source_file_hash, production_line, sheet_count, inserted_rows)
                    VALUES
                        (:source_file, :source_file_size, :source_file_hash, :production_line, :sheet_count, 0)
                    """
                ),
                {
                    "source_file": filename,
                    "source_file_size": file_size,
                    "source_file_hash": file_hash,
                    "production_line": production_line,
                    "sheet_count": sheet_count,
                },
            )
            upload_id = int(upload_result.lastrowid)

            params = []
            for parsed in parsed_documents:
                document_payload = parsed["document"]
                document_hash = hashlib.sha256(
                    json.dumps(document_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
                ).hexdigest()
                params.append(
                    {
                        "upload_id": upload_id,
                        "source_file": filename,
                        "source_file_size": file_size,
                        "source_file_hash": file_hash,
                        "production_line": production_line,
                        "sheet_name": parsed["sheet_name"],
                        "sheet_index": parsed["sheet_index"],
                        "document_hash": document_hash,
                        "document_payload": json.dumps(document_payload, ensure_ascii=True),
                        "document_payload_raw": json.dumps(document_payload, ensure_ascii=True),
                    }
                )

            inserted = 0
            if params:
                insert_result = conn.execute(
                    text(
                        f"""
                        INSERT IGNORE INTO {line_table}
                            (upload_id, source_file, source_file_size, production_line,
                             source_file_hash, sheet_name, sheet_index, document_hash, document_payload, document_payload_raw)
                        VALUES
                            (:upload_id, :source_file, :source_file_size, :production_line,
                             :source_file_hash, :sheet_name, :sheet_index, :document_hash, CAST(:document_payload AS JSON), :document_payload_raw)
                        """
                    ),
                    params,
                )
                inserted = int(insert_result.rowcount or 0)

            conn.execute(
                text(
                    f"""
                    UPDATE {_UPLOAD_TRACKING_TABLE}
                    SET inserted_rows = :inserted_rows
                    WHERE id = :upload_id
                    """
                ),
                {"inserted_rows": inserted, "upload_id": upload_id},
            )

        extracted_rows = _fetch_extracted_rows_preview(
            table_name=line_table,
            source_file=filename,
            source_file_size=file_size,
            source_file_hash=file_hash,
        )

        total_inserted += inserted
        total_skipped += skipped_sheets

        file_summaries.append(
            WorkOrderFileSummary(
                file_name=filename,
                production_line=production_line,
                target_table=line_table,
                inserted_rows=inserted,
                skipped_rows=skipped_sheets,
                parsed_sheets=parsed_sheets,
                skipped_sheets=skipped_sheets,
                sheets=sheet_summaries,
                extracted_rows=extracted_rows,
            )
        )

    return WorkOrderUploadResponse(
        message=(
            f"Processed {len(file_summaries)} file(s). "
            f"Parsed non-timeline sheets into normalized JSON documents."
        ),
        inserted_rows=total_inserted,
        skipped_rows=total_skipped,
        files=file_summaries,
    )
