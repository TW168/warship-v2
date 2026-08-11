"""Schemas for SAIA LTL freight load and count exception reports."""

from datetime import date, time
from pydantic import BaseModel


class SaiaLtlFreightRow(BaseModel):
    """A single line from a SAIA LTL freight report."""

    id: int | None = None
    program: str
    report_date: date
    report_time: time
    pickup_date: date
    pickup_manifest_number: str
    pro_number: str
    consignee_name: str
    hunits: int
    weight: float
    osd_exception: str
    source_file: str | None = None
    uploaded_at_utc: str | None = None


class SaiaLtlFreightUploadResponse(BaseModel):
    """Response from a SAIA LTL freight file upload."""

    filename: str
    rows_inserted: int
    rows_skipped: int
    rows_total: int
    success: bool
