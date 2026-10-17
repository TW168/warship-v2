"""Parser for the fixed-width "Plt In XFCMA but not In AS400" PDF report."""

import re
from bisect import bisect_right
from datetime import date, datetime
from pathlib import Path

import pdfplumber

_REPORT_DATETIME_RE = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})")
_DATA_ROW_RE = re.compile(r"^\d{6}\s+\d{6}\s+\S+")
_COLUMN_FIELDS = (
    "original_in_date",
    "last_date",
    "order_no",
    "product_code",
    "sw_plt_no",
    "machine_no",
    "cell_id",
    "site",
    "location",
    "grade",
    "as400_order_no",
    "item_id",
    "weight",
    "wip",
    "repack_plt_no",
    "change_date",
    "remark",
)


def _parse_report_date(value: str) -> date | None:
    """Parse the report's six-digit YYMMDD date without changing its value."""
    try:
        return datetime.strptime(value, "%y%m%d").date()
    except ValueError:
        return None


def parse_in_cma_not_in_as400_pdf(
    pdf_path: Path,
) -> tuple[datetime | None, list[dict[str, object | None]]]:
    """Extract all tabular rows and the report timestamp from a QPQUPRFIL PDF.

    The report's underline row marks the fixed-width column boundaries. Words
    are assigned by their horizontal PDF coordinates, preserving blank cells.
    """
    report_datetime: datetime | None = None
    parsed_rows: list[dict[str, object | None]] = []
    column_starts: list[float] | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for line in page.extract_text_lines():
                line_text = line.get("text", "").strip()
                if report_datetime is None:
                    match = _REPORT_DATETIME_RE.search(line_text)
                    if match:
                        try:
                            report_datetime = datetime.strptime(
                                f"{match.group(1)} {match.group(2)}",
                                "%m/%d/%y %H:%M:%S",
                            )
                        except ValueError:
                            pass

                if line_text.count("_") >= 40:
                    words = page.crop(
                        (0, line["top"] - 1, page.width, line["bottom"] + 1)
                    ).extract_words(x_tolerance=1, y_tolerance=1)
                    starts = [
                        float(word["x0"])
                        for word in words
                        if word["text"].strip("_") == ""
                    ]
                    if len(starts) == len(_COLUMN_FIELDS):
                        column_starts = starts
                    continue

                if not column_starts or not _DATA_ROW_RE.match(line_text):
                    continue

                words = page.crop(
                    (0, line["top"] - 1, page.width, line["bottom"] + 1)
                ).extract_words(x_tolerance=1, y_tolerance=1)
                cells: list[list[str]] = [[] for _ in _COLUMN_FIELDS]
                for word in words:
                    column_index = bisect_right(column_starts, float(word["x0"]) + 0.01) - 1
                    if 0 <= column_index < len(cells):
                        cells[column_index].append(word["text"])

                values: list[str | None] = []
                for cell in cells:
                    value = " ".join(cell).strip()
                    values.append(value if value and value.strip("_") else None)
                original_in_date = _parse_report_date(values[0] or "")
                last_date = _parse_report_date(values[1] or "")
                if original_in_date is None or last_date is None:
                    continue

                parsed_rows.append(
                    {
                        **dict(zip(_COLUMN_FIELDS, values)),
                        "original_in_date": original_in_date,
                        "last_date": last_date,
                    }
                )

    return report_datetime, parsed_rows
