"""Tests for Pallet in CMA not in AS400 report extraction and database upload."""

from contextlib import contextmanager
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook

from routers.maintenance import in_cma_not_in_as400 as upload_module
from utils.cma_not_in_as400_parser import _parse_report_date


class RecordingConnection:
    """Capture executed SQL and upload parameters without a database."""

    def __init__(self):
        self.executions = []

    def execute(self, statement, parameters=None):
        self.executions.append((str(statement), parameters))
        return SimpleNamespace(rowcount=1)


class RecordingEngine:
    """Provide a transaction context backed by a recording connection."""

    def __init__(self):
        self.connection = RecordingConnection()

    @contextmanager
    def begin(self):
        yield self.connection


class ReportDatesConnection(RecordingConnection):
    """Return deterministic report timestamp choices for selector tests."""

    def execute(self, statement, parameters=None):
        self.executions.append((str(statement), parameters))
        if "GROUP BY DATE(report_datetime)" in str(statement):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    all=lambda: [
                        {
                            "report_date": date(2026, 10, 21),
                            "report_datetime": datetime(2026, 10, 21, 6, 7, 52),
                            "row_count": 153,
                        },
                        {
                            "report_date": date(2026, 10, 17),
                            "report_datetime": datetime(2026, 10, 17, 6, 4, 12),
                            "row_count": 146,
                        },
                    ]
                )
            )
        return SimpleNamespace(rowcount=0)


class ReportDatesEngine(RecordingEngine):
    """Provide a fake connection for report-date listing."""

    def __init__(self):
        self.connection = ReportDatesConnection()


def _sample_rows():
    """Build regular and special rows spanning the dashboard's edge cases."""
    return [
        {
            "original_in_date": date(2026, 10, 14),
            "last_date": date(2026, 10, 21),
            "order_no": "RW22425002",
            "product_code": "CRB-123",
            "sw_plt_no": "0900186046",
            "machine_no": "1",
            "cell_id": "2075",
        },
        {
            "original_in_date": date(2026, 9, 20),
            "last_date": date(2026, 10, 21),
            "order_no": "RW23721011",
            "product_code": "   ",
            "sw_plt_no": "BE09COREL",
            "machine_no": "1",
            "cell_id": "2075",
        },
        {
            "original_in_date": date(2024, 10, 20),
            "last_date": date(2026, 10, 21),
            "order_no": "W69B187001",
            "product_code": "PSB-456",
            "sw_plt_no": "9802010001",
            "machine_no": "5",
            "cell_id": "327",
        },
        {
            "original_in_date": date(2026, 10, 21),
            "last_date": date(2026, 10, 21),
            "order_no": "RW12345678",
            "product_code": "AM1",
            "sw_plt_no": "9802000001",
            "machine_no": "2",
            "cell_id": "100",
        },
        {
            "original_in_date": date(2026, 10, 21),
            "last_date": date(2026, 10, 21),
            "order_no": "RZ12345678",
            "product_code": "HCB",
            "sw_plt_no": "9900000001",
            "machine_no": "3",
            "cell_id": "101",
        },
        {
            "original_in_date": date(2026, 10, 21),
            "last_date": date(2026, 10, 21),
            "order_no": "RW12345678",
            "product_code": "ELB",
            "sw_plt_no": "9100000001",
            "machine_no": "4",
            "cell_id": "102",
        },
    ]


def test_classify_series_checks_required_prefix_order_and_text_ids():
    """Special IDs are recognized without coercing pallet IDs to numbers."""
    assert upload_module.classify_series("980201980200") == "980201 - L divider 81"
    assert upload_module.classify_series("9802000001") == "980200 - L divider 80"
    assert upload_module.classify_series("9900000001") == "99 - Color roll scrap"
    assert upload_module.classify_series("9100000001") == "91 - Reclaim in a box"
    assert upload_module.classify_series("0900186046") == "regular"
    assert upload_module.classify_series("BE09COREL") == "regular"
    assert upload_module.classify_series(" ") == "regular"


def test_yymmdd_report_date_parser():
    """The report's YYMMDD dates parse and invalid calendar dates are rejected."""
    assert _parse_report_date("231219") == date(2023, 12, 19)
    assert _parse_report_date("261021") == date(2026, 10, 21)
    assert _parse_report_date("261332") is None
    assert _parse_report_date("") is None


def test_age_bucket_boundaries_and_order_type_edge_cases():
    """Age and order classification honor their specified inclusive ranges."""
    assert [upload_module.age_bucket(value) for value in (0, 7, 8, 30, 31, 90, 91, 365, 366, 730, 731)] == [
        "0-7 days",
        "0-7 days",
        "8-30 days",
        "8-30 days",
        "31-90 days",
        "31-90 days",
        "91-365 days",
        "91-365 days",
        "1-2 years",
        "1-2 years",
        "2+ years",
    ]
    assert upload_module.order_type("W69B187001") == "W"
    assert upload_module.order_type("RW22425002") == "RW"
    assert upload_module.order_type("RZ12345678") == "RZ"
    assert upload_module.order_type("") == "(blank)"


def test_xfcma_summary_and_pallets_filter_special_ids(client, monkeypatch):
    """Summary grouping excludes special IDs from regular-only metrics."""
    monkeypatch.setattr(
        upload_module,
        "_load_snapshot",
        lambda _report_date: (date(2026, 10, 21), "report_datetime", _sample_rows()),
    )
    response = client.get("/api/xfcma/summary?report_date=2026-10-21")
    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"] == {
        "all": 6,
        "regular": 2,
        "special": 4,
        "occupied_cells": 5,
    }
    assert [row["label"] for row in payload["by_series"]] == [
        "91 - Reclaim in a box",
        "99 - Color roll scrap",
        "980200 - L divider 80",
        "980201 - L divider 81",
    ]
    assert [row["count"] for row in payload["by_series"]] == [1, 1, 1, 1]
    assert sum(row["count"] for row in payload["by_age"]) == 2
    assert {"label": "(blank)", "count": 1, "percent": 50.0} in payload["by_family"]
    assert payload["cell_occupancy"]["one_pallet_cells"]["count"] == 4
    assert payload["mixed_order_cells"] == [
        {"location": "1-2075", "orders": ["RW22425002", "RW23721011"]}
    ]

    response = client.get("/api/xfcma/pallets?group=regular&report_date=2026-10-21")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert [row["sw_plt_no"] for row in rows] == ["BE09COREL", "0900186046"]
    assert rows[0]["pallets_in_cell"] == 2
    assert rows[0]["family"] == "(blank)"


def test_xfcma_summary_validates_report_date_and_group(client):
    """Invalid date input and pallet group values are rejected by FastAPI."""
    assert client.get("/api/xfcma/summary?report_date=not-a-date").status_code == 422
    assert client.get("/api/xfcma/pallets?group=unknown").status_code == 422


def test_xfcma_report_dates_are_loaded_from_report_datetime(client, monkeypatch):
    """Date selector options expose report load dates, timestamps, and counts."""
    engine = ReportDatesEngine()
    monkeypatch.setattr(upload_module, "_engine", engine)
    response = client.get("/api/xfcma/report-dates")
    assert response.status_code == 200
    assert response.json()["reports"] == [
        {
            "report_date": "2026-10-21",
            "report_datetime": "2026-10-21T06:07:52",
            "row_count": 153,
        },
        {
            "report_date": "2026-10-17",
            "report_datetime": "2026-10-17T06:04:12",
            "row_count": 146,
        },
    ]
    assert "GROUP BY DATE(report_datetime)" in engine.connection.executions[1][0]


def test_xfcma_analysis_endpoint_downloads_summary_and_data_sheets(client, monkeypatch):
    """Selected report analysis downloads the expected formatted workbook tabs."""
    monkeypatch.setattr(
        upload_module,
        "_load_snapshot",
        lambda requested: (
            requested or date(2026, 10, 21),
            "report_datetime",
            _sample_rows(),
        ),
    )
    response = client.get("/api/xfcma/analysis?report_date=2026-10-21")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == (
        'attachment; filename="SWXFREP4_2026-10-21_analysis.xlsx"'
    )

    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert workbook.sheetnames == ["Summary", "Data", "Special IDs", "Notes"]
    assert workbook["Summary"]["A1"].value == "Regular vs special"
    assert workbook["Data"].max_row == 3
    assert workbook["Special IDs"].max_row == 5
    assert workbook["Data"]["E2"].value == "BE09COREL"
    assert workbook["Data"]["E3"].value == "0900186046"
    assert workbook["Data"]["A1"].value == "Orig In-Date"
    assert workbook["Summary"]["A5"].value == "Total"
    for sheet in workbook.worksheets:
        assert sheet.oddHeader.center.text == (
            "SWXFREP4, plt In XFCMA but not In AS400 list."
        )
        assert sheet.oddFooter.right.text == "Printed: &D"
    assert workbook["Notes"]["A1"].value == (
        "SWXFREP4, plt In XFCMA but not In AS400 list."
    )
    workbook.close()


def test_legacy_summary_only_counts_regular_pallets(client, monkeypatch):
    """The pre-existing summary contract remains regular-pallet-only."""
    monkeypatch.setattr(
        upload_module,
        "_load_snapshot",
        lambda _report_date: (date(2026, 10, 21), "report_datetime", _sample_rows()),
    )
    response = client.get("/maintenance/api/in-cma-not-in-as400/summary")
    assert response.status_code == 200
    payload = response.json()
    assert sum(item["pallets"] for item in payload["by_age"]) == 2
    assert sum(item["pallets"] for item in payload["by_product_family"]) == 2


def test_pdf_upload_extracts_and_saves_rows(client, monkeypatch):
    """Extracted report fields, rather than raw PDF bytes, are inserted."""
    engine = RecordingEngine()
    monkeypatch.setattr(upload_module, "_engine", engine)
    report_datetime = datetime(2026, 10, 17, 6, 4, 12)
    parsed_rows = [
        {
            "original_in_date": date(2023, 8, 18),
            "last_date": date(2026, 10, 17),
            "order_no": "RW23807034",
            "product_code": "AM1-197106",
            "sw_plt_no": "9900000065",
            "machine_no": "3",
            "cell_id": "1447",
            "site": None,
            "location": None,
            "grade": None,
            "as400_order_no": None,
            "item_id": "0",
            "weight": "0",
            "wip": None,
            "repack_plt_no": None,
            "change_date": "0",
            "remark": "_______________________________",
        }
    ]
    monkeypatch.setattr(
        upload_module,
        "parse_in_cma_not_in_as400_pdf",
        lambda _path: (report_datetime, parsed_rows),
    )

    response = client.post(
        "/maintenance/api/in-cma-not-in-as400/upload",
        files={"file": ("QPQUPRFIL_Z7jg5Cy6.PDF", b"%PDF-1.4\nreport", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "filename": "QPQUPRFIL_Z7jg5Cy6.PDF",
        "report_datetime": "2026-10-17T06:04:12",
        "parsed_rows": 1,
        "inserted_rows": 1,
        "message": "Extracted and saved 1 report row to MySQL.",
    }
    assert "CREATE TABLE IF NOT EXISTS in_cma_not_in_as400" in engine.connection.executions[0][0]
    assert "DELETE FROM in_cma_not_in_as400" in engine.connection.executions[1][0]
    insert_sql, params = engine.connection.executions[2]
    assert "INSERT INTO in_cma_not_in_as400" in insert_sql
    assert params[0]["product_code"] == "AM1-197106"
    assert params[0]["sw_plt_no"] == "9900000065"
    assert params[0]["original_in_date"] == date(2023, 8, 18)
    assert params[0]["source_file"] == "QPQUPRFIL_Z7jg5Cy6.PDF"


def test_pdf_upload_rejects_non_pdf_file(client):
    """Files without a PDF extension are rejected before database writes."""
    response = client.post(
        "/maintenance/api/in-cma-not-in-as400/upload",
        files={"file": ("report.txt", b"%PDF-1.4\nsample", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only PDF files are allowed"


def test_pdf_upload_does_not_change_database_when_no_rows_are_extracted(client, monkeypatch):
    """An unrecognized report is rejected before starting a database transaction."""
    engine = RecordingEngine()
    monkeypatch.setattr(upload_module, "_engine", engine)
    monkeypatch.setattr(
        upload_module,
        "parse_in_cma_not_in_as400_pdf",
        lambda _path: (datetime(2026, 10, 17, 6, 4, 12), []),
    )

    response = client.post(
        "/maintenance/api/in-cma-not-in-as400/upload",
        files={"file": ("report.pdf", b"%PDF-1.4\nreport", "application/pdf")},
    )

    assert response.status_code == 400
    assert "No report rows were extracted" in response.json()["detail"]
    assert engine.connection.executions == []


def test_in_cma_page_is_available(client):
    """The existing page renders the upload form and pallet dashboard."""
    response = client.get("/maintenance/in-cma-not-in-as400")

    assert response.status_code == 200
    assert "Pallet in CMA not in AS400" in response.text
    assert 'id="palletTrendChart"' in response.text
    assert 'style="height: 380px;"' in response.text
    assert "Report: SWXFREP4, plt In XFCMA but not In AS400 list." in response.text
    assert "/api/xfcma/summary" in response.text
    assert "/api/xfcma/report-dates" in response.text
    assert "/api/xfcma/analysis" in response.text
    assert 'id="reportDateSelect"' in response.text
    assert 'id="downloadAnalysis"' in response.text
    assert response.text.index("Import report rows") < response.text.index("Choose loaded report")
    assert response.text.index("Cell occupancy") < response.text.index("By stacker")
    assert response.text.index("By stacker") < response.text.index("By order</h2>")
    assert "Over-capacity cells" not in response.text
    assert 'id="kpiOverCapacity"' not in response.text
    assert 'id="overCapacityBody"' not in response.text
    assert "By order type" not in response.text
    assert "Cells with mixed orders" not in response.text
    assert 'class="btn btn-link btn-sm p-0 text-white text-decoration-none sort-button"' in response.text
