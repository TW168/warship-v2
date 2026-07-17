"""Pandas-based parser for production work-order Excel sheets."""

from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

_TIMELINE_TOKEN = "timeline"


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""


def _clean_string(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).replace("_x000D_", " ").strip()
    normalized = " ".join(text.split())
    return normalized or None


def _to_number(value: Any) -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number) if number.is_integer() else number
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def _to_iso_date(value: Any) -> str | None:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _cell(df: pd.DataFrame, row: int, col: int) -> Any:
    """Get 1-based row/col cell with safe bounds checks."""
    r_idx = row - 1
    c_idx = col - 1
    if r_idx < 0 or c_idx < 0:
        return None
    if r_idx >= len(df.index):
        return None
    if c_idx >= len(df.columns):
        return None
    return df.iat[r_idx, c_idx]


def _clean_scalar(value: Any) -> Any:
    """Preserve numeric cells and normalize strings for JSON output."""
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return int(value) if float(value).is_integer() else float(value)
    return _clean_string(value)


def _parse_pallets(df: pd.DataFrame) -> list[dict[str, Any]]:
    pallets: list[dict[str, Any]] = []
    for row_no in range(7, len(df.index) + 1):
        barcode = _clean_string(_cell(df, row_no, 7))
        if not barcode:
            continue

        roll_nbr = _clean_string(_cell(df, row_no, 5))
        order_nbr = roll_nbr

        pallets.append(
            {
                "nbr": _to_number(_cell(df, row_no, 4)),
                "order_nbr": order_nbr,
                "roll_nbr": roll_nbr,
                "seq": _to_number(_cell(df, row_no, 6)),
                "barcode": barcode,
                "wgt_lbs": _to_number(_cell(df, row_no, 8)),
                "roll": _clean_string(_cell(df, row_no, 9)),
                "qc": _clean_string(_cell(df, row_no, 10)),
                "winder": _clean_string(_cell(df, row_no, 11)),
            }
        )

    return pallets


def _parse_material_usage_section(df: pd.DataFrame, title: str) -> list[dict[str, Any]]:
    """Extract one named material-usage section from columns 13-16."""
    section_title = title.upper()
    title_row = None

    for row_no in range(1, len(df.index) + 1):
        label = (_clean_string(_cell(df, row_no, 13)) or "").upper()
        if label == section_title:
            title_row = row_no
            break

    if title_row is None:
        return []

    rows: list[dict[str, Any]] = []
    for row_no in range(title_row + 2, len(df.index) + 1):
        hopper_value = _clean_scalar(_cell(df, row_no, 13))
        hopper_text = "" if hopper_value is None else str(hopper_value).strip()
        hopper_upper = hopper_text.upper()

        if not hopper_text:
            continue
        if hopper_upper == "TOTAL" or hopper_upper.startswith("EXT."):
            break

        rows.append(
            {
                "hopper": hopper_value,
                "silo": _clean_string(_cell(df, row_no, 14)),
                "std_pct": _to_number(_cell(df, row_no, 15)),
                "input_lbs": _to_number(_cell(df, row_no, 16)),
            }
        )

    return rows


def _parse_material_usage(df: pd.DataFrame) -> dict[str, Any]:
    """Extract nested material-usage blocks for extruder and secondary ext sections."""
    return {
        "extruder": _parse_material_usage_section(df, "EXTRUDER"),
        "ext_b": _parse_material_usage_section(df, "EXT. B"),
        "ext_c": _parse_material_usage_section(df, "EXT. C"),
        "ext_d": _parse_material_usage_section(df, "EXT. D"),
    }


def _parse_comments(df: pd.DataFrame) -> str | None:
    """Extract freeform comments below the COMMENTS label when present."""
    comment_row = None
    for row_no in range(1, len(df.index) + 1):
        label = (_clean_string(_cell(df, row_no, 1)) or "").upper()
        if label == "COMMENTS":
            comment_row = row_no
            break

    if comment_row is None:
        return None

    parts: list[str] = []
    for row_no in range(comment_row + 1, len(df.index) + 1):
        row_parts = []
        for col_no in range(1, 17):
            value = _clean_string(_cell(df, row_no, col_no))
            if value:
                row_parts.append(value)
        if not row_parts:
            continue
        parts.append(" ".join(row_parts))

    return "\n".join(parts) if parts else None


def _parse_downtime_log(df: pd.DataFrame) -> list[dict[str, Any]]:
    downtime_log: list[dict[str, Any]] = []
    header_row = None

    for row_no in range(1, len(df.index) + 1):
        c1 = (_clean_string(_cell(df, row_no, 1)) or "").lower()
        c2 = (_clean_string(_cell(df, row_no, 2)) or "").lower()
        if c1 == "code" and c2 == "time":
            header_row = row_no
            break

    if header_row is None:
        return downtime_log

    for row_no in range(header_row + 1, len(df.index) + 1):
        code = _clean_string(_cell(df, row_no, 1))
        time_mins = _to_number(_cell(df, row_no, 2))

        if code and code.upper() == "TOTAL":
            break
        if code and code.upper() == "COMMENTS":
            continue
        # Ignore non-downtime text rows; valid downtime needs both code and time.
        if code is None or time_mins is None:
            continue

        downtime_log.append({"code": code, "time_min": time_mins})

    return downtime_log


def parse_work_order_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Parse one work-order sheet dataframe into strict JSON schema order."""
    pallets = _parse_pallets(df)
    material_usage = _parse_material_usage(df)
    downtime_log = _parse_downtime_log(df)
    comments = _parse_comments(df)

    ticket = {
        "line": _clean_string(_cell(df, 2, 1)),
        "prod_date": _to_iso_date(_cell(df, 2, 3)),
        "ewo": _clean_string(_cell(df, 2, 7)),
        "shift": _clean_string(_cell(df, 2, 9)),
        "crew": _clean_string(_cell(df, 2, 11)),
        "prod_time": _to_number(_cell(df, 2, 13)),
        "operator": _clean_string(_cell(df, 2, 15)),
        "charting": [
            {
                "chart": _clean_string(_cell(df, 7, 1)),
                "film_type": _clean_string(_cell(df, 9, 1)),
                "formula": _clean_string(_cell(df, 11, 1)),
                "pack_code": _clean_string(_cell(df, 13, 1)),
                "width_in": _to_number(_cell(df, 15, 1)),
                "length_ft": _to_number(_cell(df, 17, 1)),
                "prod_weight_lbs": _to_number(_cell(df, 19, 1)),
                "op_test_weight_lbs": _to_number(_cell(df, 21, 1)),
                "qc_scrap_lbs": _to_number(_cell(df, 23, 1)),
                "total_scrap_lbs": _to_number(_cell(df, 25, 1)),
                "downtime_min": _to_number(_cell(df, 27, 1)),
                "yield_pct": _to_number(_cell(df, 29, 1)),
                "weight_to_next_lbs": _to_number(_cell(df, 31, 1)),
            }
        ],
        "downtime": downtime_log,
        "pallets": pallets,
        "material_usage": material_usage,
        "comments": comments,
    }

    return {"ticket": ticket}


def _parse_workbook(source: str | Path | BytesIO) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    excel_file = pd.ExcelFile(source)

    parsed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for idx, sheet_name in enumerate(excel_file.sheet_names, start=1):
        if _TIMELINE_TOKEN in sheet_name.lower():
            skipped.append(
                {
                    "sheet_name": sheet_name,
                    "sheet_index": idx,
                    "reason": "Sheet name contains 'Timeline'.",
                }
            )
            continue

        df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None, dtype=object)
        parsed.append(
            {
                "sheet_name": sheet_name,
                "sheet_index": idx,
                "document": parse_work_order_dataframe(df),
            }
        )

    return parsed, skipped


def parse_work_order_workbook(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse workbook from filesystem path."""
    return _parse_workbook(path)


def parse_work_order_workbook_bytes(content: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse workbook from uploaded bytes payload."""
    return _parse_workbook(BytesIO(content))
