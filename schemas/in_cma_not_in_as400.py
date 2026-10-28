"""Response schemas for In CMA not in AS400 report uploads."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class InCmaNotInAs400UploadResponse(BaseModel):
    """Response returned after report rows are stored in MySQL."""

    filename: str
    report_datetime: datetime
    parsed_rows: int
    inserted_rows: int
    message: str


class InCmaPalletSummaryItem(BaseModel):
    """A pallet count for an age range or product family."""

    label: str
    pallets: int


class InCmaNotInAs400SummaryResponse(BaseModel):
    """Pallet counts grouped by age and product family."""

    by_age: list[InCmaPalletSummaryItem]
    by_product_family: list[InCmaPalletSummaryItem]


class XfcmaGroupCount(BaseModel):
    """A labeled count and its share of the containing group."""

    label: str
    count: int
    percent: float


class XfcmaCellOverCapacity(BaseModel):
    """A cell whose pallet occupancy exceeds its two-pallet capacity."""

    location: str
    pallets: int


class XfcmaMixedOrderCell(BaseModel):
    """A cell containing pallets associated with multiple orders."""

    location: str
    orders: list[str]


class XfcmaCellOccupancy(BaseModel):
    """Cell occupancy counts and cells exceeding capacity."""

    one_pallet_cells: XfcmaGroupCount
    two_pallet_cells: XfcmaGroupCount
    over_capacity_cells: XfcmaGroupCount
    over_capacity_list: list[XfcmaCellOverCapacity]


class XfcmaSummaryResponse(BaseModel):
    """Snapshot summary of regular and special XFCMA pallets."""

    report_date: date | None
    report_date_source: Literal["report_datetime", "last_date_fallback", "none"]
    totals: dict[str, int]
    by_series: list[XfcmaGroupCount]
    by_age: list[XfcmaGroupCount]
    by_family: list[XfcmaGroupCount]
    by_stacker: list[XfcmaGroupCount]
    by_order_type: list[XfcmaGroupCount]
    cell_occupancy: XfcmaCellOccupancy
    by_order: list[XfcmaGroupCount]
    mixed_order_cells: list[XfcmaMixedOrderCell]


class XfcmaPallet(BaseModel):
    """One pallet row enriched with report age and cell occupancy."""

    orig_in_date: date
    last_handle_date: date
    order_no: str | None
    product_code: str | None
    sw_plt_no: str | None
    stacker: str | None
    cell: str | None
    location: str
    days_on_report: int
    age_bucket: str
    family: str
    order_type: str
    series: str
    pallets_in_cell: int


class XfcmaPalletsResponse(BaseModel):
    """Pallet detail rows for one XFCMA classification."""

    report_date: date | None
    report_date_source: Literal["report_datetime", "last_date_fallback", "none"]
    group: Literal["regular", "special"]
    rows: list[XfcmaPallet]


class XfcmaReportDate(BaseModel):
    """One available report calendar date and its latest load timestamp."""

    report_date: date
    report_datetime: datetime
    row_count: int


class XfcmaReportDatesResponse(BaseModel):
    """Available report dates for the XFCMA dashboard selector."""

    reports: list[XfcmaReportDate]
