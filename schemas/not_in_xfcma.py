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


class GradeGAgingBucket(BaseModel):
    """Aging distribution bucket for Grade G pallets."""
    bucket: str
    pallet_count: int
    total_weight: int


class GradeGTopProduct(BaseModel):
    """Top product summary for current Grade G worklist."""
    product_code: str
    pallet_count: int
    total_weight: int


class GradeGRepeatOffender(BaseModel):
    """Pallet recurring across multiple report days."""
    pallet: str
    product_code: str
    manu_order: str
    appearances: int
    last_in_date: date
    days_old: int


class GradeGPullListRow(BaseModel):
    """Priority pull-list row for Grade G pallets."""
    pallet: str
    location: str
    product_code: str
    manu_order: str
    item: int
    weight: int
    last_in_date: date
    days_old: int


class NotInXfcmaGradeGDashboardResponse(BaseModel):
    """Daily operations dashboard for Grade G mismatch analysis."""
    latest_report_date: date
    previous_report_date: Optional[date] = None
    total_grade_g_pallets: int
    total_grade_g_weight: int
    new_today_count: int
    carried_over_count: int
    clearance_rate_pct: Optional[float] = None
    aging_buckets: list[GradeGAgingBucket]
    top_products: list[GradeGTopProduct]
    repeat_offenders: list[GradeGRepeatOffender]
    pull_list: list[GradeGPullListRow]
