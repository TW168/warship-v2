"""Parser utilities for trucking schedule PDFs.

Expected column order in each data row:
    bl_nbr, bl_weight, carrier_id, order_nbr, pk_date, pk_time,
    rt, prld, net_weight, ship_to_cust, st

This parser reads text-layer PDFs via pdfplumber. If a PDF has no text layer
(e.g., scanned image-only files), parsing returns an empty list.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

import pdfplumber

_HEADER_HINTS = (
    "bl_nbr",
    "bl_weight",
    "carrier_id",
    "order_nbr",
    "pk_date",
    "pk_time",
    "rt",
    "prld",
    "net_weight",
    "ship_to_cust",
    "st",
)

_NUMERIC_RE = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?$")
_BL_RE = re.compile(r"^[A-Z0-9]{6,}$")
_ORDER_RE = re.compile(r"^[A-Z0-9-]{4,}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def _parse_float(raw: str | None) -> float | None:
    """Convert numeric text to float or return None for blanks/invalid values."""
    if raw is None:
        return None
    value = raw.strip().replace(",", "")
    if not value:
        return None
    if not _NUMERIC_RE.match(value):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(raw: str | None) -> date | None:
    """Parse pk_date from common date formats used in reports."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            if fmt == "%m/%d":
                return parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue
    return None


def _parse_time(raw: str | None) -> time | None:
    """Parse pk_time from 24h/12h formats commonly found in PDFs."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    for fmt in ("%H:%M:%S", "%H:%M", "%H%M", "%I:%M%p", "%I:%M %p"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _looks_like_header(line: str) -> bool:
    """Detect header lines to skip by checking known column-name hints."""
    lowered = line.lower().replace(" ", "")
    if "b/l" in line.lower() and "carrier" in line.lower() and "order" in line.lower():
        return True
    if "trucking schedule" in line.lower():
        return True
    return sum(1 for token in _HEADER_HINTS if token in lowered) >= 3


def _parse_data_line(line: str) -> dict | None:
    """Parse one line into trucking schedule fields.

    Uses fixed leading columns and a variable-width `ship_to_cust` segment
    between `net_weight` and trailing state abbreviation `st`.
    """
    tokens = line.split()
    if len(tokens) < 7:
        return None

    # Skip OCR continuation lines that begin with a short numeric token
    # (e.g., "800 T 22,457 ...") and do not have a BL number.
    if tokens[0].isdigit() and len(tokens[0]) <= 4:
        return None

    bl_nbr = tokens[0]
    bl_weight = _parse_float(tokens[1]) if len(tokens) > 1 else None
    carrier_id = tokens[2] if len(tokens) > 2 else None
    order_nbr = tokens[3] if len(tokens) > 3 else None

    idx = 4
    pk_date = _parse_date(tokens[idx]) if len(tokens) > idx else None
    if pk_date is not None:
        idx += 1

    pk_time = _parse_time(tokens[idx]) if len(tokens) > idx else None
    if pk_time is not None:
        idx += 1

    rt = tokens[idx] if len(tokens) > idx else None
    idx += 1

    tail = tokens[idx:]
    if not tail:
        return None

    st = tail[-1].upper() if len(tail[-1]) <= 3 else None
    inner_tail = tail[:-1] if st else tail

    net_weight = None
    prld = None
    ship_to_cust = None

    if inner_tail:
        if _parse_float(inner_tail[0]) is not None:
            net_weight = _parse_float(inner_tail[0])
            if len(inner_tail) > 1:
                prld = inner_tail[1]
                ship_to_cust = " ".join(inner_tail[2:]).strip() or None
        else:
            prld = inner_tail[0]
            if len(inner_tail) > 1 and _parse_float(inner_tail[1]) is not None:
                net_weight = _parse_float(inner_tail[1])
                ship_to_cust = " ".join(inner_tail[2:]).strip() or None
            else:
                ship_to_cust = " ".join(inner_tail[1:]).strip() or None

    if bl_nbr.upper() in {"B/L", "NUMBER"}:
        return None

    row = {
        "bl_nbr": bl_nbr,
        "bl_weight": bl_weight,
        "carrier_id": carrier_id,
        "order_nbr": order_nbr,
        "pk_date": pk_date,
        "pk_time": pk_time,
        "rt": rt,
        "prld": prld,
        "net_weight": net_weight,
        "ship_to_cust": ship_to_cust,
        "st": st,
    }
    if not _is_confident_row(row):
        return None

    return row


def _is_confident_row(row: dict) -> bool:
    """Return True for rows that look structurally complete and reliable."""
    bl_nbr = (row.get("bl_nbr") or "").upper().strip()
    order_nbr = (row.get("order_nbr") or "").upper().strip()
    st = (row.get("st") or "").upper().strip()
    rt = (row.get("rt") or "").upper().strip()
    bl_weight = row.get("bl_weight")
    net_weight = row.get("net_weight")

    if not _BL_RE.match(bl_nbr):
        return False
    if not any(ch.isalpha() for ch in bl_nbr) or not any(ch.isdigit() for ch in bl_nbr):
        return False
    if not _ORDER_RE.match(order_nbr):
        return False
    if not _STATE_RE.match(st):
        return False
    if rt not in {"T", "R", "L", "I", "E", "O"}:
        return False
    if bl_weight is None or bl_weight <= 0:
        return False
    if net_weight is None or net_weight <= 0:
        return False
    if not row.get("ship_to_cust"):
        return False

    return True


def parse_trucking_schedule_pdf(pdf_path: Path) -> list[dict]:
    """Parse trucking schedule rows from a text-layer PDF file."""
    rows: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if not page_text:
                continue

            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if not line or _looks_like_header(line):
                    continue

                parsed = _parse_data_line(line)
                if parsed is not None:
                    rows.append(parsed)

    return rows
