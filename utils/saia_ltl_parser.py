"""Parser for SAIA LTL freight load and count exception reports (PDF)."""

import io
import re
from datetime import datetime, date, time
from pathlib import Path


def parse_saia_ltl_pdf(file_content: bytes, source_filename: str) -> tuple[dict, list[dict]]:
    """Parse a SAIA LTL freight report PDF into header and detail rows.

    Returns a tuple of (header_dict, rows_list).
    Header dict contains: program, report_date, report_time, pickup_date,
                         pickup_manifest_number.
    Each row has: pro_number, consignee_name, hunits, weight, osd_exception.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber is required; install with 'uv add pdfplumber'")

    header = {}
    rows = []

    with pdfplumber.open(io.BytesIO(file_content)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            # Parse header on first page only
            if page_num == 0:
                header = _parse_header(text, source_filename)

            # Extract table from this page
            page_rows = _parse_table(text)
            rows.extend(page_rows)

    return header, rows


def _parse_header(text: str, filename: str) -> dict:
    """Extract program, dates, manifest, and trailer from the header block."""
    header = {
        "program": None,
        "report_date": None,
        "report_time": None,
        "pickup_date": None,
        "pickup_manifest_number": None,
    }

    # Program: "PROGRAM D3R320" or "PROGRAM D3C320"
    prog_match = re.search(r"PROGRAM\s+(D\d[A-Z]\d{3})", text)
    if prog_match:
        header["program"] = prog_match.group(1)

    # DATE: 08/10/26
    date_match = re.search(r"DATE:\s+(\d{1,2}/\d{1,2}/\d{2})", text)
    if date_match:
        date_str = date_match.group(1)
        d = datetime.strptime(date_str, "%m/%d/%y").date()
        header["report_date"] = d

    # TIME: 08:35:32
    time_match = re.search(r"TIME:\s+(\d{1,2}:\d{2}:\d{2})", text)
    if time_match:
        time_str = time_match.group(1)
        t = datetime.strptime(time_str, "%H:%M:%S").time()
        header["report_time"] = t

    # 8/07/26 Pick-Up Date
    pickup_date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2})\s+Pick-?Up Date", text)
    if pickup_date_match:
        pickup_str = pickup_date_match.group(1)
        pd = datetime.strptime(pickup_str, "%m/%d/%y").date()
        header["pickup_date"] = pd

    # 074164880 Pick-Up Manifest Number or similar
    manifest_match = re.search(r"(\d{9})\s+Pick-?Up Manifest Number", text)
    if manifest_match:
        header["pickup_manifest_number"] = manifest_match.group(1)

    return header


def _parse_table(text: str) -> list[dict]:
    """Extract the detail rows (Pro Number, Consignee, Units, Weight, Exception)."""
    rows = []

    # Each detail line starts with a PRO number (10-11 digits).
    # Pattern: {pro_number} {consignee_name} {hunits} {weight} {exception}
    # The tricky part: consignee names can be multiple words and vary in length.
    # We look for lines that start with a 10-11 digit number.

    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to match: 10-11 digit pro, then text (consignee), then numbers
        match = re.match(
            r"^(\d{10,11})\s+(.+?)\s+(\d+)\s+(\d+(?:,\d{3})*|\d+)\s+([A-Z\s]+)$",
            line,
        )
        if match:
            pro_num = match.group(1)
            consignee = match.group(2).strip()
            hunits = int(match.group(3))
            # Weight might have comma separators; remove them
            weight_str = match.group(4).replace(",", "")
            weight = float(weight_str)
            exception = match.group(5).strip()

            rows.append(
                {
                    "pro_number": pro_num,
                    "consignee_name": consignee,
                    "hunits": hunits,
                    "weight": weight,
                    "osd_exception": exception,
                }
            )

    return rows
