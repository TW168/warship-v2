"""Pydantic schemas for Production Line Work Order upload endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WorkOrderSheetSummary(BaseModel):
    """Per-sheet ingestion summary for one uploaded workbook."""

    sheet_name: str
    sheet_index: int
    inserted_rows: int
    skipped: bool
    skip_reason: str | None = None
    metadata_preview: dict[str, str]
    charting_preview: dict[str, Any]


class WorkOrderExtractedRow(BaseModel):
    """One stored parsed sheet document from extrusion_prod_ticket_<line> table."""

    id: int
    upload_id: int
    source_file: str
    source_file_size: int
    production_line: str
    sheet_name: str
    sheet_index: int
    document_hash: str
    document_payload: dict[str, Any] | str
    created_at_utc: datetime


class WorkOrderFileSummary(BaseModel):
    """Per-file ingestion result including target production-line table."""

    file_name: str
    production_line: str
    target_table: str
    inserted_rows: int
    skipped_rows: int
    parsed_sheets: int
    skipped_sheets: int
    sheets: list[WorkOrderSheetSummary]
    extracted_rows: list[WorkOrderExtractedRow]


class WorkOrderUploadResponse(BaseModel):
    """Upload API response for one or more work-order XLSX files."""

    message: str
    inserted_rows: int
    skipped_rows: int
    files: list[WorkOrderFileSummary]


class WorkOrderDailyUsageRow(BaseModel):
    """One hopper total for a selected work date across all uploaded lines."""

    production_line: str
    work_date: str
    hopper: str
    total_input_lbs: float
    total_sheets: int


class WorkOrderDailyUsageDetailRow(BaseModel):
    """One detailed material usage row from a parsed production ticket sheet."""

    production_line: str
    sheet_name: str
    material_code: str
    film_type: str | None = None
    silo: str | None = None
    hopper: str
    std_percentage: float | None = None
    input_lbs: float


class WorkOrderDailyUsageMaterialTotalRow(BaseModel):
    """Total production-reported input by material for one selected work date."""

    material_code: str
    total_input_lbs: float
    row_count: int


class WorkOrderDailyUsageLineSiloRow(BaseModel):
    """Total production-reported input by production line and silo."""

    production_line: str
    silo: str
    total_input_lbs: float
    row_count: int


class WorkOrderHopperMaterialBridgeRow(BaseModel):
    """Per-hopper material bridge row with mapping confidence metrics."""

    hopper: str
    mapped_material_code: str
    total_input_lbs: float
    mapped_input_lbs: float
    mapping_share_pct: float
    distinct_materials: int
    confidence: str


class WorkOrderBridgedMaterialTotalRow(BaseModel):
    """Material totals after applying hopper-to-material bridge mapping."""

    material_code: str
    total_input_lbs: float
    hopper_count: int
    weighted_share_pct: float


class WorkOrderDailyUsageResponse(BaseModel):
    """Response payload for the daily CFP hopper reconciliation endpoint."""

    work_date: str
    total_input_lbs: float
    rows: list[WorkOrderDailyUsageRow]
    details: list[WorkOrderDailyUsageDetailRow]
    material_totals: list[WorkOrderDailyUsageMaterialTotalRow]
    line_silo_totals: list[WorkOrderDailyUsageLineSiloRow]
    hopper_material_bridge: list[WorkOrderHopperMaterialBridgeRow]
    bridged_material_totals: list[WorkOrderBridgedMaterialTotalRow]
