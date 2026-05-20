"""Pydantic schemas for Sales Summary maintenance endpoints."""

from datetime import date, datetime, time

from pydantic import BaseModel


class SalesSummaryRow(BaseModel):
    """One parsed sales_summary row persisted in MySQL."""

    id: int
    source_file: str
    uploaded_at_utc: datetime
    job: str | None = None
    department: str | None = None
    unit: str | None = None
    run_date: date
    business_date: date
    run_time: time
    product_class: str
    product_name: str
    daily_order_qty: int
    daily_order_unit_price: float
    mtd_order_qty: int
    mtd_order_unit_price: float
    daily_shipment_qty: int
    daily_shipment_unit_price: float
    mtd_shipment_qty: int
    mtd_shipment_unit_price: float
    mtd_shipment_unit_frt: float
    monthend_backlog_qty: int
    total_backlog_qty: int
    total_backlog_unit_price: float
    target_qty_klb: float
    is_total_row: bool


class SalesSummaryListResponse(BaseModel):
    """Paginated list response for sales_summary rows."""

    records: list[SalesSummaryRow]
    total: int
    limit: int
    offset: int


class SalesSummaryUploadResponse(BaseModel):
    """Upload API response with processing summary."""

    message: str
    inserted: int
    files: list[dict]
