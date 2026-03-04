"""
AS400 Transaction Report PDF Parser

Parses the fixed-width QPQUPRFIL "Plt In As400 / Transtation Report" PDF
and exports rows to CSV and/or a MySQL table (In_AS400_Transaction).

AS400 date/time formats decoded
────────────────────────────────
  trans_date     CYMMDD  (7 digits)  C=1→2000s   e.g. 1250528 → 2025-05-28
  trans_time     HHMMSS  (6 digits)              e.g. 211627  → 21:16:27
  month_end      YYMM    (4 digits)  first-of-mo e.g. 2505    → 2025-05-01
  report_datetime  extracted from PDF top-left   e.g. 03/03/26 06:04:43
                                                      → 2026-03-03 06:04:43

Pallet#, Order, Item, and Product Code are carried-forward when blank
(continuation rows for the same pallet share those values).

MySQL table: In_AS400_Transaction  (created automatically if absent)
  id              INT AUTO_INCREMENT PK
  report_datetime DATETIME           ← from PDF header top-left
  order_no        VARCHAR(10)
  item            VARCHAR(10)
  product_code    VARCHAR(30)
  pallet_no       VARCHAR(15)        ← 10-digit AS400 pallet number
  loc             VARCHAR(10)
  grade           VARCHAR(5)
  weight          DECIMAL(12,2)
  trans_code      VARCHAR(5)
  weight_trans    DECIMAL(12,2)
  roll_length     INT                ← column "length" (reserved word → renamed)
  rolls           INT
  loc2            VARCHAR(10)
  grade2          VARCHAR(5)
  bl_no           VARCHAR(15)
  trans_date      DATE
  trans_time      TIME
  month_end       DATE               ← first day of the YYMM month
  notes           TEXT               ← free-form user notes (NULL from import)

Usage as a module:
    from utils.inas400_pdf_parser import parse_inas400_trans_pdf, import_inas400_trans_to_db
    n = parse_inas400_trans_pdf("input.PDF", "output.csv")
    n = import_inas400_trans_to_db("input.PDF")          # uses database.py engine

Usage as a script:
    uv run python utils/inas400_pdf_parser.py input.PDF          # → CSV
    uv run python utils/inas400_pdf_parser.py input.PDF --db     # → MySQL
    uv run python utils/inas400_pdf_parser.py input.PDF --db --truncate  # wipe then insert
"""

import csv
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional, Union

import pdfplumber
from sqlalchemy import text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Column names — match the 17 === separator groups in the report header
# ---------------------------------------------------------------------------
COLUMNS = [
    "order",
    "item",
    "product_code",
    "pallet_no",
    "loc",
    "grade",
    "weight",
    "trans_code",
    "weight_trans",
    "length",       # stored as roll_length in MySQL (reserved word)
    "rolls",
    "loc2",
    "grade2",
    "bl_no",
    "trans_date",
    "trans_time",
    "month_end_yymm",
]

# Comma-separated AS400 numeric strings that need de-formatting
_COMMA_COLS = {"weight", "weight_trans", "length", "rolls",
               "trans_date", "trans_time", "month_end_yymm"}

# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------
_SEP_WORD       = re.compile(r"^=+$")
_REPORT_DT_PAT  = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})")

# Lines that should be discarded (everything except the date/time header,
# which is extracted separately before this filter runs)
_SKIP_PATTERNS = [
    re.compile(r"\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}"),  # date/time stamp
    re.compile(r"Transtation Report"),
    re.compile(r"\bOrder\b.*\bItem\b"),
    re.compile(r"\bCode\b.*\bTrans\b.*\bDate\b"),
    re.compile(r"\*\s*\*\s*\*\s*E\s+N\s+D"),
    re.compile(r"PAGE\s+\d+"),
]

# ---------------------------------------------------------------------------
# AS400 date / time decoders
# ---------------------------------------------------------------------------

def _as400_date(cymmdd: str) -> Optional[date]:
    """
    Decode a 7-digit AS400 CYMMDD packed date to a Python date.
      C = 0 → 1900s,  C = 1 → 2000s
      e.g. '1250528' → date(2025, 5, 28)
    Returns None for empty or unparsable input.
    """
    cymmdd = (cymmdd or "").strip()
    if len(cymmdd) != 7:
        return None
    try:
        century_flag = int(cymmdd[0])   # 0 or 1
        yy           = int(cymmdd[1:3])
        mm           = int(cymmdd[3:5])
        dd           = int(cymmdd[5:7])
        year         = (1900 if century_flag == 0 else 2000) + yy
        return date(year, mm, dd)
    except (ValueError, IndexError):
        return None


def _as400_time(hhmmss: str) -> Optional[time]:
    """
    Decode a 6-digit AS400 HHMMSS packed time to a Python time.
      e.g. '211627' → time(21, 16, 27)
    Returns None for empty or unparsable input.
    """
    hhmmss = (hhmmss or "").strip()
    if len(hhmmss) != 6:
        return None
    try:
        return time(int(hhmmss[0:2]), int(hhmmss[2:4]), int(hhmmss[4:6]))
    except (ValueError, IndexError):
        return None


def _month_end_date(yymm: str) -> Optional[date]:
    """
    Decode a 4-digit AS400 YYMM month-end code to the first day of that month.
      e.g. '2505' → date(2025, 5, 1)
           '2602' → date(2026, 2, 1)
    Returns None for empty or unparsable input.
    """
    yymm = (yymm or "").strip()
    if len(yymm) != 4:
        return None
    try:
        yy = int(yymm[0:2])
        mm = int(yymm[2:4])
        year = 2000 + yy          # YYMM is always in the 2000s for this report
        return date(year, mm, 1)
    except (ValueError, IndexError):
        return None


def _extract_report_datetime(line_text: str) -> Optional[datetime]:
    """
    Extract the report timestamp from the PDF top-left header line.
    Expected format: 'MM/DD/YY HH:MM:SS' (US locale, 2-digit year → 2000+)
    e.g. '03/03/26 06:04:43' → datetime(2026, 3, 3, 6, 4, 43)
    """
    m = _REPORT_DT_PAT.search(line_text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%y %H:%M:%S")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# PDF word-grouping helpers
# ---------------------------------------------------------------------------

def _group_words_by_line(words: list[dict], y_tolerance: float = 3.0) -> list[list[dict]]:
    """Cluster extracted word dicts into lines using their 'top' coordinate."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = [sorted_words[0]]
    current_y: float = sorted_words[0]["top"]

    for word in sorted_words[1:]:
        if abs(word["top"] - current_y) <= y_tolerance:
            current.append(word)
        else:
            lines.append(sorted(current, key=lambda w: w["x0"]))
            current = [word]
            current_y = word["top"]

    lines.append(sorted(current, key=lambda w: w["x0"]))
    return lines


def _is_separator_line(line_words: list[dict]) -> bool:
    """Return True if the line is the === column-separator."""
    return (
        len(line_words) >= 15
        and all(_SEP_WORD.match(w["text"]) for w in line_words)
    )


def _should_skip(line_words: list[dict]) -> bool:
    """Return True if the line is a header/footer to discard."""
    text = " ".join(w["text"] for w in line_words)
    return any(p.search(text) for p in _SKIP_PATTERNS)


def _assign_to_columns(
    line_words: list[dict],
    col_ranges: list[tuple[float, float]],
) -> list[str]:
    """
    Map each word to the column whose x-centre is closest.
    Multi-word values are joined with a space.
    """
    result = [""] * len(col_ranges)
    col_centres = [(lo + hi) / 2.0 for lo, hi in col_ranges]

    for word in line_words:
        word_centre = (word["x0"] + word["x1"]) / 2.0
        best = min(range(len(col_centres)), key=lambda i: abs(col_centres[i] - word_centre))
        result[best] = (result[best] + " " + word["text"]).strip()

    return result


def _clean_number(value: str) -> str:
    """
    Strip AS400 thousands-comma formatting and normalise trailing minus.
      '1,241.00'  → '1241.00'
      '1,241.00-' → '-1241.00'
      '5,000-'    → '-5000'
      '.00'       → '.00'
      ''          → ''
    """
    if not value:
        return ""
    value = value.replace(",", "")
    if value.endswith("-"):
        value = "-" + value[:-1]
    return value


# ---------------------------------------------------------------------------
# Core PDF parser (returns raw-string rows + report datetime)
# ---------------------------------------------------------------------------

def _parse_pdf(pdf_path: Path) -> tuple[Optional[datetime], list[dict]]:
    """
    Internal: open the PDF and extract all data rows as string dicts.
    Also captures the report datetime from the first header line found.

    Returns:
        (report_datetime, rows)  where rows use COLUMNS as keys with
        cleaned raw string values (numbers have commas removed, trailing
        minus converted to leading minus).
    """
    col_ranges: list[tuple[float, float]] | None = None
    rows: list[dict] = []
    report_dt: Optional[datetime] = None

    # Carry-forward state
    last_order = last_item = last_product_code = last_pallet = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not words:
                continue

            for line_words in _group_words_by_line(words):
                if not line_words:
                    continue

                line_text = " ".join(w["text"] for w in line_words)

                # ── Capture report datetime from the top-left header ─────────
                if report_dt is None:
                    dt = _extract_report_datetime(line_text)
                    if dt:
                        report_dt = dt

                # ── Detect === separator → record column x-ranges ────────────
                if _is_separator_line(line_words):
                    if col_ranges is None:
                        col_ranges = [(w["x0"], w["x1"]) for w in line_words]
                    continue

                # ── Skip header / footer lines ───────────────────────────────
                if _should_skip(line_words):
                    continue

                if col_ranges is None:
                    continue

                # ── Assign words to columns ──────────────────────────────────
                fields = _assign_to_columns(line_words, col_ranges)
                while len(fields) < len(COLUMNS):
                    fields.append("")

                row = dict(zip(COLUMNS, fields[: len(COLUMNS)]))

                # ── Carry-forward pallet group fields ────────────────────────
                if row["order"]:
                    last_order = row["order"]
                else:
                    row["order"] = last_order

                if row["item"]:
                    last_item = row["item"]
                else:
                    row["item"] = last_item

                if row["product_code"]:
                    last_product_code = row["product_code"]
                else:
                    row["product_code"] = last_product_code

                if row["pallet_no"]:
                    last_pallet = row["pallet_no"]
                else:
                    row["pallet_no"] = last_pallet

                # ── Strip AS400 comma-formatting from numeric strings ────────
                for col in _COMMA_COLS:
                    row[col] = _clean_number(row.get(col, ""))

                rows.append(row)

    return report_dt, rows


# ---------------------------------------------------------------------------
# Public API — CSV export
# ---------------------------------------------------------------------------

def parse_inas400_trans_pdf(
    pdf_path: Union[str, Path],
    csv_path: Union[str, Path],
) -> int:
    """
    Parse an AS400 QPQUPRFIL Transtation Report PDF and write all data rows
    to a CSV file.

    Date/time columns are written as decoded strings:
      trans_date   → 'YYYY-MM-DD'  (blank if unparsable)
      trans_time   → 'HH:MM:SS'    (blank if unparsable)
      month_end    → 'YYYY-MM-DD'  first day of the YYMM month

    Args:
        pdf_path: Path to the input PDF.
        csv_path: Path for the output CSV (created or overwritten).

    Returns:
        Number of data rows written (excluding the CSV header row).
    """
    pdf_path = Path(pdf_path)
    csv_path = Path(csv_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    report_dt, rows = _parse_pdf(pdf_path)

    if not rows and report_dt is None:
        raise ValueError(
            f"No data or separator line found in {pdf_path}. "
            "Is this a valid QPQUPRFIL Transtation Report?"
        )

    # Build CSV column list: add report_datetime at front, rename month_end_yymm
    csv_columns = ["report_datetime"] + COLUMNS[:-1] + ["month_end"]

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_columns)
        writer.writeheader()

        for row in rows:
            out: dict = {}
            out["report_datetime"] = report_dt.isoformat(sep=" ") if report_dt else ""

            for col in COLUMNS:
                if col == "trans_date":
                    d = _as400_date(row[col])
                    out["trans_date"] = d.isoformat() if d else ""
                elif col == "trans_time":
                    t = _as400_time(row[col])
                    out["trans_time"] = t.strftime("%H:%M:%S") if t else ""
                elif col == "month_end_yymm":
                    d = _month_end_date(row[col])
                    out["month_end"] = d.isoformat() if d else ""
                else:
                    out[col] = row[col]

            writer.writerow(out)

    return len(rows)


# ---------------------------------------------------------------------------
# Public API — MySQL export
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS In_AS400_Transaction (
    id              INT           AUTO_INCREMENT PRIMARY KEY,
    report_datetime DATETIME      NOT NULL        COMMENT 'Report run timestamp from PDF header',
    order_no        VARCHAR(10)                   COMMENT 'Sales/work order number',
    item            VARCHAR(10)                   COMMENT 'Order item line number',
    product_code    VARCHAR(30)                   COMMENT 'Product code',
    pallet_no       VARCHAR(15)                   COMMENT 'AS400 10-digit pallet number',
    loc             VARCHAR(10)                   COMMENT 'Source location',
    grade           VARCHAR(5)                    COMMENT 'Grade at source',
    weight          DECIMAL(12,2)                 COMMENT 'Pallet weight (lbs)',
    trans_code      VARCHAR(5)                    COMMENT 'Transaction type code',
    weight_trans    DECIMAL(12,2)                 COMMENT 'Weight transferred (may be negative)',
    roll_length     INT                           COMMENT 'Roll length (ft)',
    rolls           INT                           COMMENT 'Number of rolls',
    loc2            VARCHAR(10)                   COMMENT 'Secondary/destination location',
    grade2          VARCHAR(5)                    COMMENT 'Grade at destination',
    bl_no           VARCHAR(15)                   COMMENT 'Bill of lading number',
    trans_date      DATE                          COMMENT 'Transaction date (decoded from AS400 CYMMDD)',
    trans_time      TIME                          COMMENT 'Transaction time (decoded from AS400 HHMMSS)',
    month_end       DATE                          COMMENT 'Month-end period first day (decoded from AS400 YYMM)',
    notes           TEXT                          COMMENT 'Free-form user notes',
    INDEX idx_order_no    (order_no),
    INDEX idx_pallet_no   (pallet_no),
    INDEX idx_trans_date  (trans_date),
    INDEX idx_report_dt   (report_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='AS400 QPQUPRFIL Transtation Report — pallets in AS400 not in XFCMA';
"""

_INSERT_SQL = text("""
    INSERT INTO In_AS400_Transaction
        (report_datetime, order_no, item, product_code, pallet_no,
         loc, grade, weight, trans_code, weight_trans,
         roll_length, rolls, loc2, grade2, bl_no,
         trans_date, trans_time, month_end)
    VALUES
        (:report_datetime, :order, :item, :product_code, :pallet_no,
         :loc, :grade, :weight, :trans_code, :weight_trans,
         :length, :rolls, :loc2, :grade2, :bl_no,
         :trans_date, :trans_time, :month_end)
""")


def create_in_as400_transaction_table(engine: Engine) -> None:
    """Create the In_AS400_Transaction table if it does not already exist.
    Also adds the `notes` column to pre-existing tables that lack it.
    """
    with engine.begin() as conn:
        conn.execute(text(_DDL))
        # Add notes column to tables created before this column existed
        exists = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME  = 'In_AS400_Transaction' "
            "  AND COLUMN_NAME = 'notes'"
        )).scalar()
        if not exists:
            conn.execute(text(
                "ALTER TABLE In_AS400_Transaction "
                "ADD COLUMN notes TEXT NULL "
                "COMMENT 'Free-form user notes'"
            ))


def _to_decimal(value: str) -> Optional[float]:
    """Convert cleaned numeric string to float, None if blank or only '.'."""
    v = (value or "").strip().lstrip(".")
    if not v or v in ("00", "0"):
        # Keep explicit zero
        pass
    try:
        return float(value) if value not in ("", ".") else None
    except ValueError:
        return None


def _to_int(value: str) -> Optional[int]:
    """Convert cleaned numeric string to int, None if blank."""
    try:
        return int(value) if value else None
    except ValueError:
        return None


def import_inas400_trans_to_db(
    pdf_path: Union[str, Path],
    engine: Optional[Engine] = None,
    truncate: bool = False,
) -> int:
    """
    Parse an AS400 QPQUPRFIL Transtation Report PDF and insert all rows into
    the In_AS400_Transaction MySQL table.

    The table is created automatically if it does not exist.
    All date/time columns are decoded from AS400 formats before insertion:
      trans_date   CYMMDD  → DATE
      trans_time   HHMMSS  → TIME
      month_end    YYMM    → DATE (first day of month)
      report_datetime      → DATETIME (from PDF top-left header)

    Args:
        pdf_path:  Path to the input PDF.
        engine:    SQLAlchemy engine (default: uses database.connect_to_database()).
        truncate:  If True, delete existing rows before inserting.

    Returns:
        Number of rows inserted.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if engine is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database import connect_to_database
        engine = connect_to_database()

    report_dt, rows = _parse_pdf(pdf_path)

    if report_dt is None:
        raise ValueError(
            f"Could not extract report datetime from {pdf_path}. "
            "Expected format: 'MM/DD/YY HH:MM:SS' in the PDF header."
        )

    create_in_as400_transaction_table(engine)

    # Build typed parameter dicts for bulk insert
    params: list[dict] = []
    for row in rows:
        params.append({
            "report_datetime": report_dt,
            "order":           row["order"],
            "item":            row["item"],
            "product_code":    row["product_code"],
            "pallet_no":       row["pallet_no"],
            "loc":             row["loc"],
            "grade":           row["grade"],
            "weight":          _to_decimal(row["weight"]),
            "trans_code":      row["trans_code"],
            "weight_trans":    _to_decimal(row["weight_trans"]),
            "length":          _to_int(row["length"]),
            "rolls":           _to_int(row["rolls"]),
            "loc2":            row["loc2"],
            "grade2":          row["grade2"],
            "bl_no":           row["bl_no"],
            "trans_date":      _as400_date(row["trans_date"]),
            "trans_time":      _as400_time(row["trans_time"]),
            "month_end":       _month_end_date(row["month_end_yymm"]),
        })

    with engine.begin() as conn:
        if truncate:
            conn.execute(text("DELETE FROM In_AS400_Transaction"))
        conn.execute(_INSERT_SQL, params)

    return len(params)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Convert AS400 QPQUPRFIL Transtation Report PDF → CSV or MySQL"
    )
    ap.add_argument("pdf", help="Input PDF file path")
    ap.add_argument(
        "csv", nargs="?",
        help="Output CSV path (default: same directory/stem as PDF). Ignored with --db.",
    )
    ap.add_argument(
        "--db", action="store_true",
        help="Insert into MySQL instead of (or in addition to) writing CSV.",
    )
    ap.add_argument(
        "--truncate", action="store_true",
        help="Delete existing rows before inserting (only with --db).",
    )
    args = ap.parse_args()

    pdf_file = Path(args.pdf)

    try:
        if args.db:
            n = import_inas400_trans_to_db(pdf_file, truncate=args.truncate)
            print(f"Done — inserted {n} rows into In_AS400_Transaction")
        else:
            csv_file = Path(args.csv) if args.csv else pdf_file.with_suffix(".csv")
            n = parse_inas400_trans_pdf(pdf_file, csv_file)
            print(f"Done — wrote {n} rows to {csv_file}")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
