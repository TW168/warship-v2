"""Upload and extract the "Pallet in CMA not in AS400" PDF report."""

import io
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import text

from database import connect_to_database
from schemas.in_cma_not_in_as400 import (
    InCmaNotInAs400SummaryResponse,
    InCmaNotInAs400UploadResponse,
    XfcmaGroupCount,
    XfcmaMixedOrderCell,
    XfcmaPallet,
    XfcmaPalletsResponse,
    XfcmaReportDatesResponse,
    XfcmaSummaryResponse,
)
from utils.cma_not_in_as400_parser import parse_in_cma_not_in_as400_pdf

router = APIRouter(tags=["Maintenance"])
xfcma_router = APIRouter(tags=["XFCMA"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

SPECIAL_SERIES = (
    ("980201", "980201 - L divider 81"),
    ("980200", "980200 - L divider 80"),
    ("99", "99 - Color roll scrap"),
    ("91", "91 - Reclaim in a box"),
)
SPECIAL_SERIES_DISPLAY_ORDER = (
    "91 - Reclaim in a box",
    "99 - Color roll scrap",
    "980200 - L divider 80",
    "980201 - L divider 81",
)
AGE_BUCKETS = (
    "0-7 days",
    "8-30 days",
    "31-90 days",
    "91-365 days",
    "1-2 years",
    "2+ years",
)
ANALYSIS_DATA_COLUMNS = (
    ("orig_in_date", "Orig In-Date"),
    ("last_handle_date", "Last Handle Date"),
    ("order_no", "Order No"),
    ("product_code", "Product Code"),
    ("sw_plt_no", "SW Plt No"),
    ("stacker", "Stacker"),
    ("cell", "Cell"),
    ("days_on_report", "Days on Report"),
    ("age_bucket", "Age Bucket"),
    ("family", "Family"),
    ("order_type", "Order Type"),
    ("series", "Series"),
    ("location", "Location"),
    ("pallets_in_cell", "Pallets in Cell"),
)
_SOURCE_COLUMNS = """
    original_in_date, last_date, order_no, product_code, sw_plt_no,
    machine_no, cell_id
"""

_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS in_cma_not_in_as400 (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        report_datetime DATETIME NOT NULL,
        original_in_date DATE NOT NULL,
        last_date DATE NOT NULL,
        order_no VARCHAR(40) NULL,
        product_code VARCHAR(100) NULL,
        sw_plt_no VARCHAR(40) NULL,
        machine_no VARCHAR(20) NULL,
        cell_id VARCHAR(20) NULL,
        site VARCHAR(40) NULL,
        location VARCHAR(80) NULL,
        grade VARCHAR(30) NULL,
        as400_order_no VARCHAR(40) NULL,
        item_id VARCHAR(40) NULL,
        weight VARCHAR(40) NULL,
        wip VARCHAR(40) NULL,
        repack_plt_no VARCHAR(40) NULL,
        change_date VARCHAR(40) NULL,
        remark TEXT NULL,
        source_file VARCHAR(255) NOT NULL,
        uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
        KEY ix_in_cma_not_in_as400_report_datetime (report_datetime),
        KEY ix_in_cma_not_in_as400_source_file (source_file)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_INSERT_ROW_SQL = """
    INSERT INTO in_cma_not_in_as400 (
        report_datetime, original_in_date, last_date, order_no, product_code,
        sw_plt_no, machine_no, cell_id, site, location, grade, as400_order_no,
        item_id, weight, wip, repack_plt_no, change_date, remark, source_file
    ) VALUES (
        :report_datetime, :original_in_date, :last_date, :order_no, :product_code,
        :sw_plt_no, :machine_no, :cell_id, :site, :location, :grade,
        :as400_order_no, :item_id, :weight, :wip, :repack_plt_no, :change_date,
        :remark, :source_file
    )
"""


@router.get(
    "/in-cma-not-in-as400",
    response_class=HTMLResponse,
    summary="Pallet in CMA not in AS400 Report Upload",
    description="Maintenance page for extracting pallet report rows from the CMA/AS400 PDF into MySQL.",
)
async def in_cma_not_in_as400_page(request: Request) -> HTMLResponse:
    """Render the upload form and live pallet dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="maintenance/in_cma_not_in_as400.html",
        context={"active_page": "in_cma_not_in_as400"},
    )


def classify_series(sw_plt_no: object | None) -> str:
    """Classify a pallet using the report's ordered special-ID prefixes."""
    pallet_number = str(sw_plt_no or "").strip()
    for prefix, label in SPECIAL_SERIES:
        if pallet_number.startswith(prefix):
            return label
    return "regular"


def age_bucket(days_on_report: int) -> str:
    """Map elapsed report days to the six dashboard age buckets."""
    age_days = max(0, days_on_report)
    if age_days <= 7:
        return AGE_BUCKETS[0]
    if age_days <= 30:
        return AGE_BUCKETS[1]
    if age_days <= 90:
        return AGE_BUCKETS[2]
    if age_days <= 365:
        return AGE_BUCKETS[3]
    if age_days <= 730:
        return AGE_BUCKETS[4]
    return AGE_BUCKETS[5]


def order_type(order_no: object | None) -> str:
    """Extract W orders as one-letter types and all others by their first two."""
    order = str(order_no or "").strip()
    if not order:
        return "(blank)"
    return "W" if order.startswith("W") else order[:2]


def _group_counts(counts: Counter[str], total: int) -> list[XfcmaGroupCount]:
    """Return nonzero groups ordered by descending count, preserving input order on ties."""
    return [
        XfcmaGroupCount(
            label=label,
            count=count,
            percent=(count * 100 / total) if total else 0.0,
        )
        for label, count in sorted(counts.items(), key=lambda item: -item[1])
        if count
    ]


def _report_group_counts(
    counts: Counter[str], total: int, labels: tuple[str, ...]
) -> list[XfcmaGroupCount]:
    """Return each requested label, including groups whose count is zero."""
    return [
        XfcmaGroupCount(
            label=label,
            count=counts[label],
            percent=(counts[label] * 100 / total) if total else 0.0,
        )
        for label in labels
    ]


def _load_snapshot(
    report_date: date | None,
) -> tuple[
    date | None,
    Literal["report_datetime", "last_date_fallback", "none"],
    list[dict[str, object | None]],
]:
    """Load one exact report snapshot, preferring the actual report timestamp."""
    with _engine.begin() as conn:
        conn.execute(text(_CREATE_TABLE_SQL))
        if report_date is None:
            latest = conn.execute(
                text("SELECT MAX(report_datetime) FROM in_cma_not_in_as400")
            ).scalar_one()
        else:
            latest = conn.execute(
                text(
                    "SELECT MAX(report_datetime) FROM in_cma_not_in_as400 "
                    "WHERE DATE(report_datetime) = :report_date"
                ),
                {"report_date": report_date},
            ).scalar_one()

        if latest is not None:
            rows = conn.execute(
                text(
                    f"SELECT {_SOURCE_COLUMNS} FROM in_cma_not_in_as400 "
                    "WHERE report_datetime = :report_datetime"
                ),
                {"report_datetime": latest},
            ).mappings().all()
            return latest.date(), "report_datetime", [dict(row) for row in rows]

        if report_date is not None:
            existing_load_date = conn.execute(
                text("SELECT MAX(report_datetime) FROM in_cma_not_in_as400")
            ).scalar_one()
            if existing_load_date is not None:
                raise HTTPException(
                    status_code=404, detail="No report exists for report_date"
                )
            fallback_date = conn.execute(
                text(
                    "SELECT MAX(last_date) FROM in_cma_not_in_as400 "
                    "WHERE last_date = :report_date"
                ),
                {"report_date": report_date},
            ).scalar_one()
        else:
            fallback_date = conn.execute(
                text("SELECT MAX(last_date) FROM in_cma_not_in_as400")
            ).scalar_one()
        if fallback_date is None:
            if report_date is not None:
                raise HTTPException(status_code=404, detail="No report exists for report_date")
            return None, "none", []

        rows = conn.execute(
            text(
                f"SELECT {_SOURCE_COLUMNS} FROM in_cma_not_in_as400 "
                "WHERE last_date = :report_date"
            ),
            {"report_date": fallback_date},
        ).mappings().all()
        return fallback_date, "last_date_fallback", [dict(row) for row in rows]


def _prepare_pallets(
    rows: list[dict[str, object | None]], selected_date: date
) -> list[dict[str, object]]:
    """Enrich raw rows and compute occupancy from stacker/cell pairs."""
    prepared: list[dict[str, object]] = []
    cell_rows: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        stacker = str(row["machine_no"] or "").strip()
        cell = str(row["cell_id"] or "").strip()
        orig_date = row["original_in_date"]
        if not isinstance(orig_date, date):
            raise ValueError("original_in_date must be a database date")
        days = (selected_date - orig_date).days
        product = str(row["product_code"] or "").strip()
        order = str(row["order_no"] or "").strip()
        pallet = str(row["sw_plt_no"] or "").strip()
        prepared.append(
            {
                "orig_in_date": orig_date,
                "last_handle_date": row["last_date"],
                "order_no": order or None,
                "product_code": product or None,
                "sw_plt_no": pallet or None,
                "stacker": stacker or None,
                "cell": cell or None,
                "location": f"{stacker}-{cell}",
                "days_on_report": days,
                "age_bucket": age_bucket(days),
                "family": product[:3] or "(blank)",
                "order_type": order_type(order),
                "series": classify_series(pallet),
                "pallets_in_cell": 0,
            }
        )
        cell_rows[(stacker, cell)].append(index)
    for indexes in cell_rows.values():
        for index in indexes:
            prepared[index]["pallets_in_cell"] = len(indexes)
    return prepared


def _build_summary(
    report_date: date | None,
    report_date_source: Literal["report_datetime", "last_date_fallback", "none"],
    rows: list[dict[str, object | None]],
) -> XfcmaSummaryResponse:
    """Calculate every dashboard group in Python from a single snapshot."""
    pallets = _prepare_pallets(rows, report_date) if report_date else []
    regular = [row for row in pallets if row["series"] == "regular"]
    special = [row for row in pallets if row["series"] != "regular"]

    by_series = Counter(str(row["series"]) for row in special)
    by_age = Counter(str(row["age_bucket"]) for row in regular)
    by_family = Counter(str(row["family"]) for row in regular)
    by_stacker = Counter(str(row["stacker"] or "(blank)") for row in pallets)
    by_order_type = Counter(str(row["order_type"]) for row in pallets)
    by_order = Counter(str(row["order_no"] or "(blank)") for row in pallets)
    cells: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in pallets:
        cells[(str(row["stacker"] or ""), str(row["cell"] or ""))].append(row)
    occupancies = Counter(len(cell_rows) for cell_rows in cells.values())
    over_capacity = [
        {"location": str(cell_rows[0]["location"]), "pallets": len(cell_rows)}
        for cell_rows in cells.values()
        if len(cell_rows) > 2
    ]
    mixed_orders = [
        XfcmaMixedOrderCell(
            location=str(cell_rows[0]["location"]),
            orders=sorted({str(row["order_no"] or "(blank)") for row in cell_rows}),
        )
        for cell_rows in cells.values()
        if len({str(row["order_no"] or "(blank)") for row in cell_rows}) > 1
    ]
    occupied_total = len(cells)
    order_type_groups = [
        XfcmaGroupCount(
            label=label,
            count=count,
            percent=(count * 100 / len(pallets)) if pallets else 0.0,
        )
        for label, count in sorted(by_order_type.items())
        if count
    ]

    return XfcmaSummaryResponse(
        report_date=report_date,
        report_date_source=report_date_source,
        totals={
            "all": len(pallets),
            "regular": len(regular),
            "special": len(special),
            "occupied_cells": occupied_total,
        },
        by_series=_report_group_counts(
            by_series, len(special), SPECIAL_SERIES_DISPLAY_ORDER
        ),
        by_age=_report_group_counts(by_age, len(regular), AGE_BUCKETS),
        by_family=_group_counts(by_family, len(regular)),
        by_stacker=_report_group_counts(
            by_stacker, len(pallets), ("1", "2", "3", "4", "5")
        ),
        by_order_type=order_type_groups,
        cell_occupancy={
            "one_pallet_cells": XfcmaGroupCount(
                label="1 pallet",
                count=occupancies[1],
                percent=(occupancies[1] * 100 / occupied_total) if occupied_total else 0.0,
            ),
            "two_pallet_cells": XfcmaGroupCount(
                label="2 pallets",
                count=occupancies[2],
                percent=(occupancies[2] * 100 / occupied_total) if occupied_total else 0.0,
            ),
            "over_capacity_cells": XfcmaGroupCount(
                label="Over 2 pallets",
                count=len(over_capacity),
                percent=(len(over_capacity) * 100 / occupied_total) if occupied_total else 0.0,
            ),
            "over_capacity_list": over_capacity,
        },
        by_order=_group_counts(by_order, len(pallets)),
        mixed_order_cells=mixed_orders,
    )


def _write_analysis_workbook(
    report_date: date,
    pallets: list[dict[str, object]],
    summary: XfcmaSummaryResponse,
) -> io.BytesIO:
    """Create a formatted four-sheet workbook matching the supplied analysis layout."""
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    data_sheet = workbook.create_sheet("Data")
    special_sheet = workbook.create_sheet("Special IDs")
    notes_sheet = workbook.create_sheet("Notes")
    print_title = "SWXFREP4, plt In XFCMA but not In AS400 list."
    for sheet in workbook.worksheets:
        sheet.oddHeader.center.text = print_title
        sheet.oddHeader.center.size = 12
        sheet.oddHeader.center.font = "Arial,Bold"
        sheet.oddFooter.right.text = "Printed: &[Date]"

    header_fill = PatternFill("solid", fgColor="154E9A")
    section_fill = PatternFill("solid", fgColor="DCE6F1")
    total_fill = PatternFill("solid", fgColor="E9EFF7")
    danger_fill = PatternFill("solid", fgColor="F8D7DA")
    thin_gray = Side(style="thin", color="D9E1F2")
    table_border = Border(bottom=thin_gray)

    def section(title: str) -> None:
        if summary_sheet.max_row:
            summary_sheet.append([None])
        summary_sheet.append([title])
        row = summary_sheet.max_row
        cell = summary_sheet.cell(row, 1)
        cell.font = Font(name="Arial", size=11, bold=True, color="154E9A")
        cell.fill = section_fill

    def table(
        headers: tuple[str, str, str],
        entries: list[tuple[object, object, object]],
        total: tuple[object, object, object] | None = None,
        percentage_column: bool = True,
    ) -> None:
        summary_sheet.append(list(headers))
        header_row = summary_sheet.max_row
        for cell in summary_sheet[header_row][:3]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
        for entry in entries:
            summary_sheet.append(list(entry))
        if total is not None:
            summary_sheet.append(list(total))
            for cell in summary_sheet[summary_sheet.max_row][:3]:
                cell.font = Font(bold=True)
                cell.fill = total_fill
        for row in summary_sheet.iter_rows(
            min_row=header_row + 1, max_row=summary_sheet.max_row, min_col=1, max_col=3
        ):
            if percentage_column:
                row[2].number_format = "0.0%"
            for cell in row:
                cell.border = table_border

    regular_count = summary.totals["regular"]
    special_count = summary.totals["special"]
    all_count = summary.totals["all"]
    summary_sheet.append(["Regular vs special"])
    summary_sheet["A1"].font = Font(name="Arial", size=12, bold=True, color="154E9A")
    table(
        ("Tab", "Pallets", "% of total"),
        [
            ("Data (regular)", regular_count, regular_count / all_count if all_count else 0),
            ("Special IDs", special_count, special_count / all_count if all_count else 0),
        ],
        ("Total", all_count, None),
    )
    summary_sheet["E1"] = (
        "Days on report and product family count the Data tab only (regular pallets). "
        "Stacker, order type and order count include both tabs. Cell occupancy counts "
        "distinct stacker/cell locations across both tabs."
    )
    summary_sheet["E1"].alignment = Alignment(wrap_text=True, vertical="top")
    summary_sheet.column_dimensions["E"].width = 54

    section("Special IDs by series")
    table(
        ("Series", "Pallets", "% of total"),
        [
            (
                group.label,
                group.count,
                group.count / special_count if special_count else 0,
            )
            for group in summary.by_series
        ],
        ("Total", special_count, None),
    )

    section("By days on report (Data tab only)")
    table(
        ("Age bucket", "Pallets", "% of total"),
        [
            (group.label, group.count, group.count / regular_count if regular_count else 0)
            for group in summary.by_age
        ],
        ("Total", regular_count, None),
    )

    section("By product family (Data tab only)")
    table(
        ("Family", "Pallets", "% of total"),
        [
            (group.label, group.count, group.count / regular_count if regular_count else 0)
            for group in summary.by_family
        ],
        ("Total", regular_count, None),
    )

    section("Cell occupancy (both tabs)")
    table(
        ("Pallets in cell", "Cells", "Note"),
        [
            ("1 pallet", summary.cell_occupancy.one_pallet_cells.count, ""),
            ("2 pallets (cell full)", summary.cell_occupancy.two_pallet_cells.count, ""),
            (
                "Over 2 (check)",
                summary.cell_occupancy.over_capacity_cells.count,
                "pallets in cells holding more than 2 — should be 0",
            ),
            ("Total cells", summary.totals["occupied_cells"], ""),
        ],
        percentage_column=False,
    )
    for cell in summary_sheet[summary_sheet.max_row]:
        cell.font = Font(bold=True)
        cell.fill = total_fill

    section("By order type")
    table(
        ("Order type", "Pallets", "% of total"),
        [
            (group.label, group.count, group.count / all_count if all_count else 0)
            for group in summary.by_order_type
        ],
        ("Total", all_count, None),
    )

    section("By stacker (Mach No#)")
    table(
        ("Stacker", "Pallets", "% of total"),
        [
            (int(group.label), group.count, group.count / all_count if all_count else 0)
            for group in summary.by_stacker
        ],
        ("Total", all_count, None),
    )

    section("By order (most pallets first)")
    table(
        ("Order No", "Pallets", "% of total"),
        [
            (group.label, group.count, group.count / all_count if all_count else 0)
            for group in summary.by_order
        ],
        ("Total", all_count, None),
    )

    summary_sheet.column_dimensions["A"].width = 36
    summary_sheet.column_dimensions["B"].width = 22
    summary_sheet.column_dimensions["C"].width = 24
    for row in summary_sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=cell.column == 5 or cell.column == 3 and cell.value is not None and isinstance(cell.value, str),
            )

    def fill_pallet_sheet(sheet, group_rows: list[dict[str, object]]) -> None:
        """Write and style one pallet-detail sheet."""
        sheet.append([label for _, label in ANALYSIS_DATA_COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for pallet in group_rows:
            values = []
            for key, _ in ANALYSIS_DATA_COLUMNS:
                value = pallet[key]
                if key in {"stacker", "cell"} and isinstance(value, str) and value.isdigit():
                    value = int(value)
                values.append(value)
            sheet.append(values)
            row = sheet.max_row
            if pallet["pallets_in_cell"] > 2:
                for cell in sheet[row]:
                    cell.fill = danger_fill
            for cell in sheet[row]:
                cell.border = table_border
            sheet.cell(row, 1).number_format = "yyyy-mm-dd"
            sheet.cell(row, 2).number_format = "yyyy-mm-dd"
            sheet.cell(row, 5).number_format = "@"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        widths = (13, 16, 16, 30, 16, 11, 10, 16, 16, 12, 12, 28, 14, 18)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width

    fill_pallet_sheet(data_sheet, [row for row in pallets if row["series"] == "regular"])
    fill_pallet_sheet(special_sheet, [row for row in pallets if row["series"] != "regular"])

    notes = [
        [print_title],
        ["Report date", report_date, "Selected from report_datetime"],
        ["Total pallets (both tabs)", all_count],
        ["  Regular pallets (Data tab)", regular_count],
        ["  Special-series pallets (Special IDs tab)", special_count],
        [None],
        ["Column definitions"],
        ["Orig In-Date: first date the pallet appeared on this report; Days on Report = report date minus Orig In-Date."],
        ["Last Handle Date: date any action was last taken on the pallet."],
        ["Order No: W-prefixed orders use W; all others use the first two characters."],
        ["Mach No is the stacker; Cell is the cell within that stacker; Location is Stacker-Cell."],
        ["SW Plt No is stored as text; leading zeros and non-numeric IDs are preserved. Weight is not reported or summed."],
        [None],
        ["Classification"],
        ["Special ID prefixes are checked in order: 980201, 980200, 99, 91. All other pallet IDs are regular."],
        ["Age buckets and product family counts apply to regular pallets. Stacker, order, and occupancy summaries include both sheets."],
        [None],
        ["Cell occupancy"],
        [f"{summary.cell_occupancy.one_pallet_cells.count} cells contain one pallet; {summary.cell_occupancy.two_pallet_cells.count} cells contain two pallets; {summary.cell_occupancy.over_capacity_cells.count} cells exceed capacity."],
        ["Mixed-order cells"],
        [
            "; ".join(
                f"{cell.location}: {', '.join(cell.orders)}"
                for cell in summary.mixed_order_cells
            )
            or "None"
        ],
        [None],
        ["Source: in_cma_not_in_as400 rows selected by report_datetime for the requested report date."],
    ]
    for row in notes:
        notes_sheet.append(row)
    notes_sheet.column_dimensions["A"].width = 96
    notes_sheet.column_dimensions["B"].width = 18
    notes_sheet.column_dimensions["C"].width = 40
    notes_sheet["A1"].font = Font(bold=True, size=12, color="154E9A")
    notes_sheet["B2"].number_format = "yyyy-mm-dd"
    for row in notes_sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


@xfcma_router.get(
    "/api/xfcma/analysis",
    summary="Download XFCMA report analysis workbook",
    description=(
        "Download a formatted Excel workbook for the selected report date with "
        "Summary, Data, Special IDs, and Notes sheets."
    ),
)
async def download_xfcma_analysis(
    report_date: date = Query(..., description="Report date in YYYY-MM-DD format"),
) -> StreamingResponse:
    """Return the requested snapshot as a formatted multi-sheet Excel workbook."""
    selected_date, _, rows = _load_snapshot(report_date)
    if selected_date is None:
        raise HTTPException(status_code=404, detail="No report exists for report_date")
    pallets = _prepare_pallets(rows, selected_date)
    pallets.sort(key=lambda row: int(row["days_on_report"]), reverse=True)
    summary = _build_summary(selected_date, "report_datetime", rows)
    workbook = _write_analysis_workbook(selected_date, pallets, summary)
    filename = f"SWXFREP4_{selected_date.isoformat()}_analysis.xlsx"
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@xfcma_router.get(
    "/api/xfcma/report-dates",
    response_model=XfcmaReportDatesResponse,
    summary="List available XFCMA report dates",
    description="Return available calendar dates from report_datetime, newest first.",
)
async def get_xfcma_report_dates() -> XfcmaReportDatesResponse:
    """Return one date option per loaded day with its latest timestamp and row count."""
    with _engine.begin() as conn:
        conn.execute(text(_CREATE_TABLE_SQL))
        rows = conn.execute(
            text(
                """
                SELECT DATE(report_datetime) AS report_date,
                       MAX(report_datetime) AS report_datetime,
                       COUNT(*) AS row_count
                FROM in_cma_not_in_as400
                GROUP BY DATE(report_datetime)
                ORDER BY report_date DESC
                """
            )
        ).mappings().all()
    return XfcmaReportDatesResponse(reports=[dict(row) for row in rows])


@xfcma_router.get(
    "/api/xfcma/summary",
    response_model=XfcmaSummaryResponse,
    summary="Summarize XFCMA pallet snapshot",
    description="Group one report snapshot into regular, special-ID, age, family, order, and cell metrics.",
)
async def get_xfcma_summary(
    report_date: date | None = Query(default=None, description="Report date in YYYY-MM-DD format"),
) -> XfcmaSummaryResponse:
    """Return all dashboard groupings for the requested or latest report date."""
    selected_date, date_source, rows = _load_snapshot(report_date)
    return _build_summary(selected_date, date_source, rows)


@xfcma_router.get(
    "/api/xfcma/pallets",
    response_model=XfcmaPalletsResponse,
    summary="List XFCMA pallet rows",
    description="Return regular or special pallet details for one report snapshot, oldest report age first.",
)
async def get_xfcma_pallets(
    group: Literal["regular", "special"],
    report_date: date | None = Query(default=None, description="Report date in YYYY-MM-DD format"),
) -> XfcmaPalletsResponse:
    """Return enriched pallet rows filtered to one regular/special group."""
    selected_date, date_source, rows = _load_snapshot(report_date)
    pallets = _prepare_pallets(rows, selected_date) if selected_date else []
    filtered = [
        XfcmaPallet(**row)
        for row in pallets
        if (row["series"] == "regular") == (group == "regular")
    ]
    filtered.sort(key=lambda row: row.days_on_report, reverse=True)
    return XfcmaPalletsResponse(
        report_date=selected_date,
        report_date_source=date_source,
        group=group,
        rows=filtered,
    )


@router.get(
    "/api/in-cma-not-in-as400/summary",
    response_model=InCmaNotInAs400SummaryResponse,
    summary="Summarize regular pallet rows in CMA not in AS400",
    description="Return regular pallet counts only, grouped by age and product family for the latest report.",
)
async def get_in_cma_not_in_as400_summary() -> InCmaNotInAs400SummaryResponse:
    """Keep the legacy summary route aligned with regular-only dashboard groups."""
    report_date, _, rows = _load_snapshot(None)
    summary = _build_summary(report_date, "report_datetime", rows)
    return InCmaNotInAs400SummaryResponse(
        by_age=[
            {"label": item.label, "pallets": item.count}
            for item in summary.by_age
        ],
        by_product_family=[
            {"label": item.label, "pallets": item.count}
            for item in summary.by_family
        ],
    )


@router.post(
    "/api/in-cma-not-in-as400/upload",
    response_model=InCmaNotInAs400UploadResponse,
    summary="Extract and save Pallet in CMA not in AS400 PDF",
    description=(
        "Extract the fixed-width QPQUPRFIL report rows and save the structured "
        "values in the in_cma_not_in_as400 MySQL table. Re-uploading a filename "
        "replaces rows previously imported from that filename."
    ),
)
async def upload_in_cma_not_in_as400_pdf(
    file: UploadFile = File(...),
) -> InCmaNotInAs400UploadResponse:
    """Extract report rows from the uploaded PDF and replace that file's database rows."""
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="A filename is required")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename must be 255 characters or fewer")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")
    if b"%PDF-" not in contents[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(contents)
            temp_path = Path(temp_file.name)

        report_datetime, parsed_rows = parse_in_cma_not_in_as400_pdf(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if report_datetime is None:
        raise HTTPException(status_code=400, detail="The PDF report timestamp was not found")
    if not parsed_rows:
        raise HTTPException(
            status_code=400,
            detail="No report rows were extracted; no database rows were changed",
        )

    insert_rows = [
        {
            **row,
            "report_datetime": report_datetime,
            "source_file": filename,
        }
        for row in parsed_rows
    ]

    with _engine.begin() as conn:
        conn.execute(text(_CREATE_TABLE_SQL))
        conn.execute(
            text("DELETE FROM in_cma_not_in_as400 WHERE source_file = :source_file"),
            {"source_file": filename},
        )
        conn.execute(text(_INSERT_ROW_SQL), insert_rows)

    row_label = "row" if len(insert_rows) == 1 else "rows"
    return InCmaNotInAs400UploadResponse(
        filename=filename,
        report_datetime=report_datetime,
        parsed_rows=len(parsed_rows),
        inserted_rows=len(insert_rows),
        message=f"Extracted and saved {len(insert_rows)} report {row_label} to MySQL.",
    )
