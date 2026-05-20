"""Tests for MKORSHDK sales summary PDF parsing."""

from pathlib import Path

from utils.sales_summary_pdf_parser import parse_sales_summary_pdf


def test_parse_sales_summary_pdf_extracts_rows_and_meta() -> None:
    """Parser should extract metadata and at least one data row from sample PDF."""
    pdf_path = Path("raw/MKORSHDK_U2qtQXxy.PDF")

    meta, rows = parse_sales_summary_pdf(pdf_path)

    assert rows, "Expected parsed rows from sample MKORSHDK PDF"
    assert meta["run_date"] is not None
    assert meta["business_date"] is not None
    assert meta["run_time"] is not None

    sample = rows[0]
    expected_keys = {
        "product_class",
        "product_name",
        "daily_order_qty",
        "daily_order_unit_price",
        "mtd_order_qty",
        "mtd_order_unit_price",
        "daily_shipment_qty",
        "daily_shipment_unit_price",
        "mtd_shipment_qty",
        "mtd_shipment_unit_price",
        "mtd_shipment_unit_frt",
        "monthend_backlog_qty",
        "total_backlog_qty",
        "total_backlog_unit_price",
        "target_qty_klb",
        "is_total_row",
    }

    assert expected_keys.issubset(sample.keys())
