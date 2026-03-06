"""
utils/extract_lmi_scores.py

Scans raw_data/lmi/ for all LMI documents (.txt and .pdf), extracts the
overall LMI score from each, and writes raw_data/lmi_scores.csv.

Columns: date (YYYY-MM-01), lmi_score, source_file

Run with:
    uv run python utils/extract_lmi_scores.py
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber

LMI_DIR = Path(__file__).parent.parent / "raw_data" / "lmi"
OUTPUT_CSV = Path(__file__).parent.parent / "raw_data" / "lmi_scores.csv"

# Matches "LMI® at 58.8", "LMI at 62.0", etc. — catches the headline score
SCORE_RE = re.compile(r'LMI[^\n]{0,10}at\s+([\d]+\.[\d]+)', re.IGNORECASE)

MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_FULL = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date_from_filename(name: str) -> date | None:
    """
    Parse the report month/year from the filename.

    Handles two patterns:
      - lmi_xxx_yyyy.txt  (abbreviated month)
      - "Month YYYY Logistics Managers Index…" (PDF full-name style)
    """
    stem = Path(name).stem.lower()

    # Pattern: lmi_xxx_yyyy
    m = re.match(r"lmi_([a-z]+)_(\d{4})$", stem)
    if m:
        month = MONTH_ABBR.get(m.group(1))
        if month:
            return date(int(m.group(2)), month, 1)

    # Pattern: "month yyyy ..."
    m = re.match(r"([a-z]+)\s+(\d{4})", stem)
    if m:
        month = MONTH_FULL.get(m.group(1))
        if month:
            return date(int(m.group(2)), month, 1)

    return None


def extract_text(path: Path) -> str:
    """Return plain text from a .txt or .pdf file (first 5 pages for PDFs)."""
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".pdf":
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:5]:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n".join(pages)
    return ""


def extract_score(text: str) -> float | None:
    """Return the first LMI overall score found in text, or None."""
    m = SCORE_RE.search(text)
    return float(m.group(1)) if m else None


def main() -> None:
    supported = {".pdf", ".txt"}
    rows = []

    for path in sorted(LMI_DIR.glob("*")):
        if path.suffix.lower() not in supported:
            continue

        report_date = parse_date_from_filename(path.name)
        if not report_date:
            print(f"WARNING: could not parse date from '{path.name}'", file=sys.stderr)
            continue

        text = extract_text(path)
        score = extract_score(text)
        if score is None:
            print(f"WARNING: could not find LMI score in '{path.name}'", file=sys.stderr)
            continue

        rows.append({
            "date": report_date.strftime("%Y-%m-%d"),
            "lmi_score": score,
            "source_file": path.name,
        })

    rows.sort(key=lambda r: r["date"])

    # Deduplicate: keep the first seen entry per month (earlier filename wins)
    seen: set[str] = set()
    unique_rows = []
    for r in rows:
        if r["date"] not in seen:
            seen.add(r["date"])
            unique_rows.append(r)
        else:
            print(f"  (skipping duplicate for {r['date']}: {r['source_file']})", file=sys.stderr)
    rows = unique_rows

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "lmi_score", "source_file"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows → {OUTPUT_CSV}\n")
    for r in rows:
        print(f"  {r['date']}  {r['lmi_score']:5.1f}  {r['source_file']}")


if __name__ == "__main__":
    main()
