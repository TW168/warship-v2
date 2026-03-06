"""
routers/tsr_prep.py — TSR Prep page routes.

Handles:
  GET  /tsr-prep                      — Ship list page with Google Maps
  POST /api/tsr-prep/upload           — Upload IPG EZ Excel → clean → insert to ipg_ez
  GET  /api/tsr-prep/filter-options   — Distinct sites, product groups, report dates
  GET  /api/tsr-prep/avail-to-ship    — Available-to-ship rows with lat/lon from us_cities
"""

import datetime
import io
import os
import re

import openpyxl
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database

router = APIRouter(tags=["TSR Prep"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()

# ─── Excel column → DB column name mapping ───────────────────────────────────
# Mirrors the column renames in the legacy Streamlit helper.py
_RENAME: dict[str, str] = {
    "SITE":                              "Site",
    "B/L Number":                        "BL_Number",
    "Truck Appointment Date (YY/MM/DD)": "Truck_Appointment_Date",
    "B/L Weight (LB)":                   "BL_Weight",
    "Freight Amount ($)":                "Freight_Amount",
    "Truck Appt. Time":                  "Truck_Appt_Time",
    "PickUp Date (YY/MM/DD)":            "Pickup_Date",
    "State":                             "State",
    "Ship to City":                      "Ship_to_City",
    "Ship to Customer":                  "Ship_to_Customer",
    "Order Number":                      "Order_Number",
    "Order Item":                        "Order_Item",
    "CSR":                               "CSR",
    "Freight Term":                      "Freight_Term",
    "Require Date (YY/MM/DD)":           "Require_Date",
    "Schedule Date (YY/MM/DD)":          "Schedule_Date",
    "Unshipped Weight (Lb)":             "Unshipped_Weight",
    "Product Code":                      "Product_Code",
    "Pick Weight (Lb)":                  "Pick_Weight",
    "Number of Pallet":                  "Number_of_Pallet",
    "Pickup By":                         "Pickup_By",
    "Change Date (YY/MM/DD)":            "Change_Date",
    "Carrier ID":                        "Carrier_ID",
    "Arrange By":                        "Arrange_By",
    "Unit Freight (cent/Lb)":            "Unit_Freight",
    "Waybill Number":                    "Waybill_Number",
    "Sales Code":                        "Sales_Code",
    "Transportation Code":               "Transportation_Code",
    "Transaction Type":                  "Transaction_Type",
    "Product Group":                     "Product_Group",
}

# DB columns whose raw Excel value must be parsed as a date
_DATE_COLS: frozenset[str] = frozenset({
    "Truck_Appointment_Date",
    "Pickup_Date",
    "Require_Date",
    "Schedule_Date",
    "Change_Date",
})

# DB columns that must be coerced to a number
_NUM_COLS: frozenset[str] = frozenset({
    "Pick_Weight", "Number_of_Pallet", "BL_Weight",
    "Freight_Amount", "Unshipped_Weight", "Unit_Freight",
})

# IPG EZ filename pattern:
# "AmTopp Current Pickup Detail Report as of 2025-3-6 H9M0.xlsx"
_FILENAME_RE = re.compile(
    r"as of (\d{4}-\d{1,2}-\d{1,2})\s+H(\d{1,2})M(\d{1,2})", re.IGNORECASE
)

# Available-to-ship query: ipg_ez ⟕ us_cities for lat/lon
_AVAIL_SQL = text("""
    SELECT
        Site,
        BL_Number,
        CSR,
        Ship_to_Customer  AS customer,
        Ship_to_City      AS city,
        State             AS state,
        SUM(Pick_Weight)      AS wgt,
        SUM(Number_of_Pallet) AS plt,
        u.lat,
        u.lon
    FROM ipg_ez i
    LEFT JOIN us_cities u
           ON i.State = u.state_id AND i.Ship_to_City = u.city_ascii
    WHERE Site          = :site
      AND Product_Group = :product_group
      AND BL_Number     NOT LIKE 'WZ%'
      AND rpt_run_date  = :rpt_date
      AND rpt_run_time  = :rpt_time
      AND Product_Code  NOT LIKE '%INSER%'
      AND Truck_Appointment_Date IS NULL
    GROUP BY Site, BL_Number, CSR, Ship_to_Customer, Ship_to_City, State, u.lat, u.lon
    ORDER BY State, Ship_to_City
""")


# ─── helpers ─────────────────────────────────────────────────────────────────

def _parse_date(val) -> datetime.date | None:
    """Coerce an openpyxl cell value to a Python date.

    Handles Python date/datetime objects (Excel date-formatted cells)
    and 'YY/MM/DD' text strings used in the IPG EZ report.
    """
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.datetime.strptime(str(val).strip(), "%y/%m/%d").date()
    except Exception:
        return None


def _parse_num(val, cast=float):
    """Coerce a cell value to a number; return 0 on failure."""
    if val is None:
        return 0
    try:
        return cast(val)
    except (TypeError, ValueError):
        return 0


def _extract_rpt_datetime(filename: str) -> tuple[datetime.date, str] | None:
    """Parse report date and snap to a standard reporting time slot.

    Returns (date, rpt_time_str) where rpt_time_str is one of:
      '09:00:00', '12:00:00', '16:00:00'
    Returns None if the filename doesn't match the expected pattern.
    """
    m = _FILENAME_RE.search(filename)
    if not m:
        return None
    try:
        # strptime handles non-zero-padded months/days (e.g. "2026-3-6")
        # fromisoformat() requires strictly zero-padded "2026-03-06" and would fail here
        rpt_date = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None
    hour = int(m.group(2))
    if hour < 11:
        rpt_time = "09:00:00"
    elif hour < 14:
        rpt_time = "12:00:00"
    else:
        rpt_time = "16:00:00"
    return rpt_date, rpt_time


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get(
    "/tsr-prep",
    response_class=HTMLResponse,
    summary="TSR Prep page",
    description=(
        "Ship list dashboard: upload IPG EZ Excel reports, filter by site/group/date/time, "
        "and view available-to-ship inventory on a Google Maps map with nearest-neighbor "
        "distance analysis."
    ),
)
async def tsr_prep(request: Request) -> HTMLResponse:
    """Render the TSR Prep page, passing the Google Maps API key from the environment."""
    maps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return templates.TemplateResponse(
        "tsr_prep/index.html",
        {"request": request, "active_page": "tsr_prep", "maps_key": maps_key},
    )


@router.post(
    "/api/tsr-prep/upload",
    summary="Upload IPG EZ Excel report",
    description=(
        "Accepts an AmTopp IPG EZ Excel file (.xlsx/.xls). Parses report date/time from "
        "the filename, cleans column names, and bulk-inserts rows into ipg_ez. "
        "Returns {status, rows_inserted} where status is 'ok' or 'duplicate'."
    ),
)
async def upload_ipg_ez(file: UploadFile = File(...)) -> JSONResponse:
    """Read, clean, and insert an IPG EZ Excel report into ipg_ez."""
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return JSONResponse(
            status_code=422,
            content={"error": "Only .xlsx / .xls files are accepted."},
        )

    rpt_info = _extract_rpt_datetime(file.filename)
    if rpt_info is None:
        return JSONResponse(
            status_code=422,
            content={
                "error": (
                    "Could not parse date/time from filename. "
                    "Expected: '...as of YYYY-M-D HhMm.xlsx'"
                )
            },
        )
    rpt_date, rpt_time = rpt_info

    content = await file.read()
    file_size = len(content)

    try:
        # Duplicate check by filename + byte size
        with _engine.connect() as conn:
            dup = conn.execute(
                text("SELECT 1 FROM ipg_ez WHERE file_name = :fn AND file_size = :fs LIMIT 1"),
                {"fn": file.filename, "fs": file_size},
            ).fetchone()
        if dup:
            return JSONResponse(content={"status": "duplicate", "rows_inserted": 0})

        # ── Parse Excel with openpyxl ────────────────────────────────────────────
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)

        # Row 1 = headers; drop the last trailing summary column present in IPG EZ reports
        raw_headers = [str(h) if h is not None else "" for h in next(rows_iter)]
        headers = raw_headers[:-1]

        now = datetime.datetime.now()
        records: list[dict] = []

        for raw_row in rows_iter:
            raw_row = raw_row[:-1]          # drop trailing column value
            row = dict(zip(headers, raw_row))

            # IPG EZ reports contain subtotal/blank rows — skip them
            if not row.get("SITE"):
                continue

            renamed: dict = {}
            for excel_col, val in row.items():
                db_col = _RENAME.get(excel_col, excel_col)
                if db_col in _DATE_COLS:
                    val = _parse_date(val)
                elif db_col in _NUM_COLS:
                    val = _parse_num(val)
                elif db_col == "Truck_Appt_Time":
                    if isinstance(val, datetime.datetime):
                        val = val.strftime("%H:%M:%S")
                    elif isinstance(val, datetime.time):
                        val = val.strftime("%H:%M:%S")
                    else:
                        # Reject text like 'N/A' — MySQL TIME column won't accept it
                        val = None
                renamed[db_col] = val

            renamed["rpt_run_date"]      = rpt_date
            renamed["rpt_run_time"]      = rpt_time
            renamed["file_name"]         = file.filename
            renamed["file_size"]         = file_size
            renamed["uploaded_date_time"] = now
            records.append(renamed)

        wb.close()

        if not records:
            return JSONResponse(content={"status": "ok", "rows_inserted": 0})

        # ── Bulk INSERT ──────────────────────────────────────────────────────────
        cols = list(records[0].keys())
        col_list = ", ".join(f"`{c}`" for c in cols)
        val_list = ", ".join(f":{c}" for c in cols)
        insert_sql = text(f"INSERT INTO ipg_ez ({col_list}) VALUES ({val_list})")

        with _engine.begin() as conn:
            conn.execute(insert_sql, records)

    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(content={"status": "ok", "rows_inserted": len(records)})


@router.get(
    "/api/tsr-prep/filter-options",
    summary="Filter dropdown options",
    description="Returns distinct sites, product groups, and report dates from ipg_ez.",
)
async def filter_options() -> JSONResponse:
    """Fetch distinct values for the TSR Prep filter dropdowns."""
    try:
        with _engine.connect() as conn:
            sites = [r[0] for r in conn.execute(
                text("SELECT DISTINCT Site FROM ipg_ez ORDER BY Site")
            ).fetchall()]
            groups = [r[0] for r in conn.execute(
                text("SELECT DISTINCT Product_Group FROM ipg_ez ORDER BY Product_Group")
            ).fetchall()]
            dates = [str(r[0]) for r in conn.execute(
                text("SELECT DISTINCT rpt_run_date FROM ipg_ez ORDER BY rpt_run_date DESC")
            ).fetchall()]
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(content={"sites": sites, "groups": groups, "dates": dates})


@router.get(
    "/api/tsr-prep/avail-to-ship",
    summary="Available-to-ship list",
    description=(
        "Queries ipg_ez joined to us_cities for lat/lon. Filters by site, product group, "
        "report date, and report time. Excludes WZ* BLs, INSERT* products, and any row "
        "that already has a Truck Appointment Date assigned."
    ),
)
async def avail_to_ship(
    site: str = Query(..., description="Site code, e.g. AMJK"),
    product_group: str = Query(..., description="Product group, e.g. SW"),
    rpt_date: str = Query(..., description="Report date YYYY-MM-DD"),
    rpt_time: str = Query(..., description="Report time, e.g. 09:00:00"),
) -> JSONResponse:
    """Execute the available-to-ship query and return JSON rows."""
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                _AVAIL_SQL,
                {
                    "site": site,
                    "product_group": product_group,
                    "rpt_date": rpt_date,
                    "rpt_time": rpt_time,
                },
            ).fetchall()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    result = [
        {
            "bl_number": r.BL_Number,
            "csr":       r.CSR,
            "customer":  r.customer,
            "city":      r.city,
            "state":     r.state,
            "wgt":       float(r.wgt or 0),
            "plt":       int(r.plt or 0),
            "lat":       float(r.lat) if r.lat is not None else None,
            "lon":       float(r.lon) if r.lon is not None else None,
        }
        for r in rows
    ]
    return JSONResponse(content=result)
