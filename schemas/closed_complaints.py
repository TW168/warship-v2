"""Pydantic models for closed complaints upload."""

from decimal import Decimal

from pydantic import BaseModel


class ClosedComplaintsUploadResponse(BaseModel):
    status: str
    message: str
    rows_read: int
    rows_inserted: int
    duplicate_rows: int


class ClosedComplaintsYearOption(BaseModel):
    year: int


class ClosedComplaintsYearsResponse(BaseModel):
    years: list[ClosedComplaintsYearOption]


class ClosedComplaintsSummaryRow(BaseModel):
    prod_group: str
    complaint_count: int
    unique_complaints: int
    mtd_order_qty: int
    total_claim_amount: Decimal
    total_approved_amount: Decimal
    return_count: int
    return_claim_amount: Decimal
    return_approved_amount: Decimal


class ClosedComplaintsSummaryResponse(BaseModel):
    selected_year: int | None
    rows: list[ClosedComplaintsSummaryRow]


class ClosedComplaintsCodeSummaryRow(BaseModel):
    prod_group: str
    code: str
    code_description: str
    complaint_count: int
    total_claim_amount: Decimal
    total_approved_amount: Decimal
    return_count: int


class ClosedComplaintsCodeSummaryResponse(BaseModel):
    selected_year: int
    rows: list[ClosedComplaintsCodeSummaryRow]


class ClosedComplaintsCodeOption(BaseModel):
    code: str
    description: str


class ClosedComplaintsCodeSummaryOptionsResponse(BaseModel):
    years: list[int]
    months: list[int]
    prod_groups: list[str]
    codes: list[ClosedComplaintsCodeOption]


class ClosedComplaintsTrendPoint(BaseModel):
    prod_group: str
    date: str
    mtd_order_qty_lbs: int
    complaints: int
    claim_amount: Decimal
    approved_amount: Decimal
    returns: int
    complaint_rate: float


class ClosedComplaintsTrendResponse(BaseModel):
    selected_year: int
    points: list[ClosedComplaintsTrendPoint]
