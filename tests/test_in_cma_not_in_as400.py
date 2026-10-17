"""Tests for original PDF storage on the In CMA not in AS400 page."""

from contextlib import contextmanager
from types import SimpleNamespace

from routers.maintenance import in_cma_not_in_as400 as upload_module


class RecordingConnection:
    """Capture executed SQL and upload parameters without a database."""

    def __init__(self):
        self.executions = []

    def execute(self, statement, parameters=None):
        self.executions.append((str(statement), parameters))
        return SimpleNamespace(lastrowid=42)


class RecordingEngine:
    """Provide a transaction context backed by a recording connection."""

    def __init__(self):
        self.connection = RecordingConnection()

    @contextmanager
    def begin(self):
        yield self.connection


def test_pdf_upload_stores_original_bytes(client, monkeypatch):
    """The upload endpoint stores bytes and metadata without parsing the PDF."""
    engine = RecordingEngine()
    monkeypatch.setattr(upload_module, "_engine", engine)
    pdf_bytes = b"%PDF-1.4\nsample pdf content"

    response = client.post(
        "/maintenance/api/in-cma-not-in-as400/upload",
        files={"file": ("QPQUPRFIL_Z7jg5Cy6.PDF", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": 42,
        "filename": "QPQUPRFIL_Z7jg5Cy6.PDF",
        "size_bytes": len(pdf_bytes),
        "message": "PDF saved to MySQL.",
    }
    assert "CREATE TABLE IF NOT EXISTS in_cma_not_in_as400_documents" in engine.connection.executions[0][0]
    insert_sql, params = engine.connection.executions[1]
    assert "INSERT INTO in_cma_not_in_as400_documents" in insert_sql
    assert params["pdf_data"] == pdf_bytes
    assert params["original_filename"] == "QPQUPRFIL_Z7jg5Cy6.PDF"
    assert params["file_size"] == len(pdf_bytes)


def test_pdf_upload_rejects_non_pdf_file(client):
    """Files without the PDF extension are rejected before database writes."""
    response = client.post(
        "/maintenance/api/in-cma-not-in-as400/upload",
        files={"file": ("report.txt", b"%PDF-1.4\nsample", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only PDF files are allowed"


def test_in_cma_page_is_available(client):
    """The Maintenance menu destination renders successfully."""
    response = client.get("/maintenance/in-cma-not-in-as400")

    assert response.status_code == 200
    assert "In CMA not in AS400" in response.text
