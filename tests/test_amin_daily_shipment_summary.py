"""Tests for AMIN daily shipment summary parsing and upload."""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from routers.maintenance import amin_daily_shipment_summary as summary_module


_REPORT_TEXT = """\
11/18/26 06:01:37 AMIN daily shipment summary 11/18/26 PAGE 1
Ship Qty Freight AVG Frt Shipped
date Shipped TOTAL cent/lb Avg
------- --------- ------- -------- -------
26/11/02 119,272 9,769.63 8.1911 119,272
26/11/03 234,797 15,345.93 6.5358 234,797
1,650,956 155,032.03 9.3904 137,580
* * * E N D O F R E P O R T * * *
"""


class RecordingConnection:
    """Capture SQL statements and parameters for upload assertions."""

    def __init__(self):
        self.executions = []

    def execute(self, statement, parameters=None):
        self.executions.append((str(statement), parameters))
        return SimpleNamespace(rowcount=1)


class RecordingEngine:
    """Provide one recording connection through transaction contexts."""

    def __init__(self):
        self.connection = RecordingConnection()

    @contextmanager
    def begin(self):
        yield self.connection


class MappingResult:
    """Expose dictionaries through the SQLAlchemy mappings().all() interface."""

    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class SummaryQueryConnection(RecordingConnection):
    """Return configured rows for report-period and monthly data queries."""

    def __init__(self, periods=None, records=None):
        super().__init__()
        self.periods = periods or []
        self.records = records or []

    def execute(self, statement, parameters=None):
        self.executions.append((str(statement), parameters))
        if "SELECT DISTINCT" in str(statement):
            return MappingResult(self.periods)
        return MappingResult(self.records)


class SummaryQueryEngine(RecordingEngine):
    """Provide query results through SQLAlchemy connection contexts."""

    def __init__(self, periods=None, records=None):
        self.connection = SummaryQueryConnection(periods=periods, records=records)

    @contextmanager
    def connect(self):
        yield self.connection


def test_amin_daily_shipment_page_is_available_from_maintenance(client, monkeypatch):
    """Render the new upload page and create its table on first visit."""
    engine = RecordingEngine()
    monkeypatch.setattr(summary_module, "_engine", engine)

    response = client.get("/maintenance/amin-daily-shipment-summary")

    assert response.status_code == 200
    assert "AMIN Daily Shipment Summary" in response.text
    assert 'href="/maintenance/amin-daily-shipment-summary"' in response.text
    assert 'id="reportYearSelect"' in response.text
    assert 'id="reportMonthSelect"' in response.text
    assert 'id="shipmentTableBody"' in response.text
    assert 'id="shipmentChart"' in response.text
    assert "label: 'Qty Shipped (lbs)'" in response.text
    assert "Freight Total ($)" in response.text
    assert "<th scope=\"col\" class=\"text-end\">Shipped Avg</th>" not in response.text
    assert (
        "CREATE TABLE IF NOT EXISTS amin_daily_shipment_summary"
        in engine.connection.executions[0][0]
    )


def test_parse_amin_daily_shipment_report_preserves_header_and_total():
    """Parse printed header values, detail lines, and the aggregate line."""
    metadata, rows = summary_module._parse_amin_daily_shipment_text_pages([_REPORT_TEXT])

    assert metadata == {
        "report_generated_at": datetime(2026, 11, 18, 6, 1, 37),
        "report_name": "AMIN daily shipment summary 11/18/26",
        "pdf_page_count": 1,
    }
    assert len(rows) == 3
    assert rows[0]["ship_date"].isoformat() == "2026-11-02"
    assert rows[0]["qty_shipped"] == 119272
    assert rows[0]["freight_total"] == Decimal("9769.63")
    assert rows[0]["avg_frt_cent_lb"] == Decimal("8.1911")
    assert rows[-1]["row_type"] == "total"
    assert rows[-1]["ship_date"] is None
    assert rows[-1]["qty_shipped"] == 1650956
    assert rows[-1]["shipped_avg"] == 137580


def test_amin_daily_shipment_upload_creates_table_and_replaces_report(client, monkeypatch):
    """Upload should create the table and replace rows for the report timestamp."""
    engine = RecordingEngine()
    monkeypatch.setattr(summary_module, "_engine", engine)
    parsed_report = summary_module._parse_amin_daily_shipment_text_pages([_REPORT_TEXT])
    monkeypatch.setattr(
        summary_module,
        "_parse_amin_daily_shipment_pdf",
        lambda _path: parsed_report,
    )

    response = client.post(
        "/maintenance/api/amin-daily-shipment-summary/upload",
        files={"file": ("daily.PDF", b"pdf bytes", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["inserted_rows"] == 3
    assert response.json()["detail_rows"] == 2
    assert response.json()["total_rows"] == 1
    assert [statement.split()[0] for statement, _ in engine.connection.executions] == [
        "CREATE",
        "DELETE",
        "INSERT",
    ]
    assert engine.connection.executions[1][1] == {
        "report_generated_at": datetime(2026, 11, 18, 6, 1, 37)
    }
    inserted_rows = engine.connection.executions[2][1]
    assert inserted_rows[0]["source_file"] == "daily.PDF"
    assert inserted_rows[-1]["row_type"] == "total"


def test_amin_daily_shipment_upload_rejects_invalid_pdf(client, monkeypatch):
    """Unreadable PDF input should return a clear client error."""
    monkeypatch.setattr(summary_module, "_engine", RecordingEngine())

    response = client.post(
        "/maintenance/api/amin-daily-shipment-summary/upload",
        files={"file": ("daily.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file could not be read as a valid PDF."


def test_amin_daily_shipment_periods_api_lists_available_report_months(client, monkeypatch):
    """The month selector should receive newest available report periods."""
    engine = SummaryQueryEngine(
        periods=[{"report_year": 2026, "report_month": 11}, {"report_year": 2026, "report_month": 10}]
    )
    monkeypatch.setattr(summary_module, "_engine", engine)

    response = client.get("/maintenance/api/amin-daily-shipment-summary/periods")

    assert response.status_code == 200
    assert response.json() == [
        {"year": 2026, "month": 11},
        {"year": 2026, "month": 10},
    ]
    assert "ORDER BY report_year DESC, report_month DESC" in engine.connection.executions[-1][0]


def test_amin_daily_shipment_month_api_returns_latest_report_rows(client, monkeypatch):
    """Selected report month should return the latest snapshot and its total row."""
    generated_at = datetime(2026, 11, 18, 6, 1, 37)
    engine = SummaryQueryEngine(
        records=[
            {
                "id": 1,
                "report_generated_at": generated_at,
                "report_name": "AMIN daily shipment summary 11/18/26",
                "page_number": 1,
                "pdf_page_count": 1,
                "line_number": 1,
                "row_type": "detail",
                "ship_date": date(2026, 11, 2),
                "qty_shipped": 119272,
                "freight_total": Decimal("9769.63"),
                "avg_frt_cent_lb": Decimal("8.1911"),
                "shipped_avg": 119272,
                "source_file": "daily.pdf",
            },
            {
                "id": 2,
                "report_generated_at": generated_at,
                "report_name": "AMIN daily shipment summary 11/18/26",
                "page_number": 1,
                "pdf_page_count": 1,
                "line_number": 2,
                "row_type": "total",
                "ship_date": None,
                "qty_shipped": 119272,
                "freight_total": Decimal("9769.63"),
                "avg_frt_cent_lb": Decimal("8.1911"),
                "shipped_avg": 119272,
                "source_file": "daily.pdf",
            },
        ]
    )
    monkeypatch.setattr(summary_module, "_engine", engine)

    response = client.get(
        "/maintenance/api/amin-daily-shipment-summary/data?year=2026&month=11"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_generated_at"] == "2026-11-18T06:01:37"
    assert [row["row_type"] for row in payload["records"]] == ["detail", "total"]
    query, parameters = engine.connection.executions[-1]
    assert "MAX(report_generated_at)" in query
    assert parameters == {"year": 2026, "month": 11}


def test_amin_daily_shipment_monthly_trend_api_returns_one_point_per_month(client, monkeypatch):
    """Trend points should use each month's latest report aggregate."""
    engine = SummaryQueryEngine(
        records=[
            {
                "year": 2026,
                "month": 10,
                "report_generated_at": datetime(2026, 10, 30, 6, 0),
                "report_name": "AMIN daily shipment summary 10/30/26",
                "page_number": 1,
                "line_number": 13,
                "qty_shipped": 900000,
                "avg_frt_cent_lb": Decimal("8.5"),
            },
            {
                "year": 2026,
                "month": 11,
                "report_generated_at": datetime(2026, 11, 18, 6, 1, 37),
                "report_name": "AMIN daily shipment summary 11/18/26",
                "page_number": 1,
                "line_number": 13,
                "qty_shipped": 1650956,
                "avg_frt_cent_lb": Decimal("9.3904"),
            },
            {
                "year": 2026,
                "month": 11,
                "report_generated_at": datetime(2026, 11, 18, 6, 1, 37),
                "report_name": "AMIN daily shipment summary 11/18/26",
                "page_number": 1,
                "line_number": 12,
                "qty_shipped": 1595615,
                "avg_frt_cent_lb": Decimal("9.2"),
            },
        ]
    )
    monkeypatch.setattr(summary_module, "_engine", engine)

    response = client.get("/maintenance/api/amin-daily-shipment-summary/monthly-trend")

    assert response.status_code == 200
    points = response.json()
    assert [(point["year"], point["month"]) for point in points] == [(2026, 10), (2026, 11)]
    assert points[1]["qty_shipped"] == 1650956
    assert points[1]["avg_frt_cent_lb"] == "9.3904"
    query = engine.connection.executions[-1][0]
    assert "MAX(report_generated_at)" in query
    assert "WHERE summary.row_type = 'total'" in query


def test_parser_rejects_non_amin_report():
    """A PDF with a different report title must not be stored as AMIN data."""
    unrelated_report = _REPORT_TEXT.replace("AMIN daily shipment summary", "Other report")

    with pytest.raises(ValueError, match="not an AMIN"):
        summary_module._parse_amin_daily_shipment_text_pages([unrelated_report])
