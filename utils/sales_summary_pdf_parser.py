"""PDF parser for MKORSHDK daily sales summary reports.

Parses product-level rows from IBM-generated PDF text extracted with pdfplumber.
Expected data row shape (after product text):
    daily_order_qty, daily_order_unit,
    mtd_order_qty, mtd_order_unit,
    daily_shipment_qty, daily_shipment_unit,
    mtd_shipment_qty, mtd_shipment_unit,
    mtd_shipment_unit_frt,
    monthend_backlog_qty, total_backlog_qty,
    total_backlog_unit, target_qty_klb
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pdfplumber

_NUMERIC_TOKEN = re.compile(r"-?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?|-?\.\d+")
_SKIP_PREFIXES = (
    "CURRENT MONTH WORKING DAYS",
    "AS OF TODAY WORKING DAYS",
    "AVG TARGET SHIPMENT/WORKING DAY",
)


def _to_int(raw: str) -> int:
    """Parse integer with comma cleanup; defaults to 0 when invalid."""
    try:
        return int(float(raw.replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _to_float(raw: str) -> float:
    """Parse float with comma cleanup; defaults to 0.0 when invalid."""
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def parse_sales_summary_pdf(pdf_path: Path) -> tuple[dict, list[dict]]:
    """Parse one MKORSHDK PDF and return metadata and normalized row dictionaries."""
    meta: dict = {
        "job": None,
        "run_date": None,
        "department": None,
        "unit": None,
        "business_date": None,
        "run_time": None,
    }
    rows: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                if "JOB:" in line:
                    job_match = re.search(r"JOB\s*:\s*(.+?)\s+RUN DATE", line)
                    if job_match:
                        meta["job"] = job_match.group(1).strip()

                    run_date_match = re.search(r"RUN DATE\s*:\s*(\d{1,2}/\d{1,2}/\d{2})", line)
                    if run_date_match:
                        try:
                            meta["run_date"] = datetime.strptime(run_date_match.group(1), "%m/%d/%y").date()
                        except ValueError:
                            pass

                    dept_match = re.search(r"DEPARTMENT\s*:\s*(.+?)\s+UNIT\s*:", line)
                    if dept_match:
                        meta["department"] = dept_match.group(1).strip()

                    unit_match = re.search(r"UNIT\s*:\s*([A-Za-z]+)", line)
                    if unit_match:
                        meta["unit"] = unit_match.group(1).strip()

                    run_time_match = re.search(r"RUN TIME\s*:\s*(\d{1,2}:\d{2}:\d{2})", line)
                    if run_time_match:
                        try:
                            meta["run_time"] = datetime.strptime(run_time_match.group(1), "%H:%M:%S").time()
                        except ValueError:
                            pass
                    continue

                if line.startswith("=") or line.startswith("<-"):
                    continue
                if line.startswith(_SKIP_PREFIXES):
                    continue
                if "TARGETPRODUCT" in line:
                    continue

                tokens = _NUMERIC_TOKEN.findall(line)
                if len(tokens) < 13:
                    continue

                tail = tokens[-13:]
                product_text = _NUMERIC_TOKEN.split(line, maxsplit=1)[0].strip()
                if not product_text:
                    continue

                if " " in product_text:
                    product_class, product_name = product_text.split(" ", 1)
                else:
                    product_class, product_name = "", product_text

                row = {
                    "product_class": product_class.strip(),
                    "product_name": product_name.strip(),
                    "daily_order_qty": _to_int(tail[0]),
                    "daily_order_unit_price": _to_float(tail[1]),
                    "mtd_order_qty": _to_int(tail[2]),
                    "mtd_order_unit_price": _to_float(tail[3]),
                    "daily_shipment_qty": _to_int(tail[4]),
                    "daily_shipment_unit_price": _to_float(tail[5]),
                    "mtd_shipment_qty": _to_int(tail[6]),
                    "mtd_shipment_unit_price": _to_float(tail[7]),
                    "mtd_shipment_unit_frt": _to_float(tail[8]),
                    "monthend_backlog_qty": _to_int(tail[9]),
                    "total_backlog_qty": _to_int(tail[10]),
                    "total_backlog_unit_price": _to_float(tail[11]),
                    "target_qty_klb": _to_float(tail[12]),
                    "is_total_row": product_text.upper().startswith("AMTOP TTL"),
                }
                rows.append(row)

    if meta["run_date"] is None:
        meta["run_date"] = date.today()
    meta["business_date"] = meta["run_date"] - timedelta(days=1)
    if meta["run_time"] is None:
        meta["run_time"] = time(0, 0, 0)

    return meta, rows
