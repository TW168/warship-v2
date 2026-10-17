"""Tests for In CMA not in AS400 report extraction and database upload."""

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

from routers.maintenance import in_cma_not_in_as400 as upload_module


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
    """The Maintenance upload page renders report-extraction instructions."""
    response = client.get("/maintenance/in-cma-not-in-as400")

    assert response.status_code == 200
    assert "In CMA not in AS400" in response.text
    assert "Extract the QPQUPRFIL report rows" in response.text
