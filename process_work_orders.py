#!/usr/bin/env python3
"""Convert all .xlsx files in the current directory to strict work-order JSON schema."""

from __future__ import annotations

import json
import re
from pathlib import Path

from utils.work_order_json_parser import parse_work_order_workbook


def _sanitize_sheet_name(sheet_name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", sheet_name.strip())
    text = text.strip("_")
    return text or "sheet"


def main() -> int:
    current_dir = Path.cwd()
    xlsx_files = sorted(current_dir.glob("*.xlsx"))

    if not xlsx_files:
        print(f"No .xlsx files found in {current_dir}")
        return 0

    converted_files = 0
    converted_sheets = 0
    for xlsx_path in xlsx_files:
        parsed_sheets, skipped_sheets = parse_work_order_workbook(xlsx_path)

        for sheet in parsed_sheets:
            sheet_tag = _sanitize_sheet_name(str(sheet["sheet_name"]))
            output_name = f"{xlsx_path.stem}_{sheet_tag}.json"
            output_path = xlsx_path.with_name(output_name)
            output_path.write_text(
                json.dumps(sheet["document"], indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            converted_sheets += 1
            print(f"Exported {xlsx_path.name} / {sheet['sheet_name']} -> {output_name}")

        if skipped_sheets:
            skipped_names = ", ".join(str(item["sheet_name"]) for item in skipped_sheets)
            print(f"Skipped sheets in {xlsx_path.name}: {skipped_names}")

        converted_files += 1

    print(f"Done. Processed {converted_files} workbook(s), exported {converted_sheets} sheet JSON file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
