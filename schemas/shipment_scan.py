"""
schemas/shipment_scan.py -- Pydantic models for shipment scan API.

Matches table: shipment_scan
Columns: id, uploaded_at, source_file, file_size, status, created_at,
         scan_datetime, pallet, bol, name
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ShipmentScanRecord(BaseModel):
    id: int
    uploaded_at: Optional[datetime] = None
    source_file: str
    file_size: Optional[int] = None
    row_count: Optional[int] = 1
    scan_datetime: Optional[datetime] = None
    pallet: Optional[str] = None
    bol: Optional[str] = None
    status: Optional[str] = None
    name: Optional[str] = None


class ShipmentScanListResponse(BaseModel):
    records: list[ShipmentScanRecord]
    total: int
    limit: int
    offset: int


class ShipmentScanUploadResponse(BaseModel):
    status: str
    message: str
    rows_inserted: int


class ShipmentScanErrorResponse(BaseModel):
    error: str


class ShipmentScanDailyBolPoint(BaseModel):
    scan_date: str
    bol_count: int


class ShipmentScanDailyBolResponse(BaseModel):
    series: list[ShipmentScanDailyBolPoint]
    total_days: int
    total_unique_bols: int
