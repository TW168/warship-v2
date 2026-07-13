"""Pydantic models for the Trucking Schedule maintenance feature."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class TruckingScheduleRow(BaseModel):
    """One trucking_schedule table row."""

    id: int
    source_file: str
    uploaded_at_utc: datetime
    bl_nbr: Optional[str] = None
    bl_weight: Optional[float] = None
    carrier_id: Optional[str] = None
    order_nbr: Optional[str] = None
    pk_date: Optional[date] = None
    pk_time: Optional[time] = None
    rt: Optional[str] = None
    prld: Optional[str] = None
    net_weight: Optional[float] = None
    ship_to_cust: Optional[str] = None
    st: Optional[str] = None


class TruckingScheduleListResponse(BaseModel):
    """Paginated trucking schedule rows."""

    records: list[TruckingScheduleRow]
    total: int
    limit: int
    offset: int


class TruckingScheduleUploadResponse(BaseModel):
    """Upload response payload for trucking schedule PDF ingest."""

    message: str
    inserted: int
    files: list[dict]
