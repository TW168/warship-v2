"""Response schema for AMIN daily shipment summary uploads."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class AminDailyShipmentSummaryUploadResponse(BaseModel):
    """Processing summary returned after a report is stored."""

    message: str
    file: str
    report_generated_at: datetime
    report_name: str
    pdf_page_count: int
    detail_rows: int
    total_rows: int
    inserted_rows: int


class AminDailyShipmentSummaryPeriod(BaseModel):
    """A year/month containing at least one uploaded report."""

    year: int
    month: int


class AminDailyShipmentSummaryRecord(BaseModel):
    """One shipment detail or aggregate line stored from a report."""

    id: int
    report_generated_at: datetime
    report_name: str
    page_number: int
    pdf_page_count: int
    line_number: int
    row_type: Literal["detail", "total"]
    ship_date: date | None
    qty_shipped: int
    freight_total: Decimal
    avg_frt_cent_lb: Decimal
    shipped_avg: int
    source_file: str


class AminDailyShipmentSummaryMonthResponse(BaseModel):
    """Latest report snapshot and all its rows for one report month."""

    year: int
    month: int
    report_generated_at: datetime
    report_name: str
    pdf_page_count: int
    records: list[AminDailyShipmentSummaryRecord]


class AminDailyShipmentSummaryMonthlyPoint(BaseModel):
    """Monthly report-total values from the latest report snapshot."""

    year: int
    month: int
    report_generated_at: datetime
    report_name: str
    qty_shipped: int
    avg_frt_cent_lb: Decimal
