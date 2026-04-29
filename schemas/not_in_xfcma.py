"""Pydantic schema for not_in_xfcma table."""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class NotInXfcmaRow(BaseModel):
    """Response model for a not_in_xfcma row."""
    id: int
    report_datetime: datetime
    product_code: str
    manu_order: str
    item: int
    pallet: str
    location: str
    rolls: int
    length: int
    weight: int
    grade: str
    last_in_date: date
    created_at_utc: datetime
    source_file: str


class NotInXfcmaCreateRequest(BaseModel):
    """Request model for creating a not_in_xfcma row."""
    report_datetime: datetime
    product_code: str
    manu_order: str
    item: int
    pallet: str
    location: str
    rolls: int
    length: int
    weight: int
    grade: str
    last_in_date: date


class NotInXfcmaUpdateRequest(BaseModel):
    """Request model for updating a not_in_xfcma row."""
    report_datetime: Optional[datetime] = None
    product_code: Optional[str] = None
    manu_order: Optional[str] = None
    item: Optional[int] = None
    pallet: Optional[str] = None
    location: Optional[str] = None
    rolls: Optional[int] = None
    length: Optional[int] = None
    weight: Optional[int] = None
    grade: Optional[str] = None
    last_in_date: Optional[date] = None


class NotInXfcmaDeleteResponse(BaseModel):
    """Response model for delete operation."""
    id: int
    message: str
