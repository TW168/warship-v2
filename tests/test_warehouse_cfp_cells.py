from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook
import pytest

from routers import warehouse
from routers.warehouse import count_prefix_pallets, extract_prefix_pallets


def test_reclaim_boxes_printer_button_targets_excel_export(client):
    """Reclaim Boxes printer button downloads the Excel workbook endpoint."""
    response = client.get("/warehouse")
    assert response.status_code == 200
    assert "downloadReclaimBoxesExcel(this)" in response.text
    assert "/api/warehouse/reclaim-boxes/export.xlsx" in response.text


def test_other_warehouse_printer_buttons_target_excel_exports(client):
    """The other CFP cards use their configured Excel export keys."""
    response = client.get("/warehouse")
    assert response.status_code == 200
    for export_key in (
        "color-rolls-scrap",
        "sheet-81-3313-080",
        "sheet-81-331-081",
    ):
        assert f"downloadWarehousePalletExcel('{export_key}', this)" in response.text


def test_warehouse_excel_download_shows_button_spinner_without_page_navigation(client):
    """Excel generation uses a button spinner and fetch instead of browser navigation."""
    response = client.get("/warehouse")
    assert response.status_code == 200
    assert 'spinner-border spinner-border-sm d-none' in response.text
    assert "async function downloadPalletWorkbook(url, button)" in response.text
    assert "button.setAttribute('aria-busy', 'true')" in response.text
    assert "const response = await fetch(url)" in response.text
    assert "window.location.href = `/api/warehouse/" not in response.text


def test_count_prefix_pallets_counts_910_values():
    html = """
    <table>
      <thead>
        <tr><th>Cell ID</th><th>Stacker</th><th>Cell</th><th>Height</th><th>Status</th><th>Pallet 1</th><th>Pallet 2</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>10001</td><td>1</td><td>1</td><td>52</td><td>Active</td><td>9101001</td><td></td>
        </tr>
        <tr>
          <td>10002</td><td>1</td><td>2</td><td>52</td><td>Active</td><td>9102002</td><td>9103003</td>
        </tr>
        <tr>
          <td>10003</td><td>1</td><td>3</td><td>52</td><td>Active</td><td>12345</td><td>00000001</td>
        </tr>
      </tbody>
    </table>
    """

    matches = extract_prefix_pallets(html, prefix="910")
    assert [item["pallet"] for item in matches] == ["9101001", "9102002", "9103003"]
    assert [item["location"] for item in matches] == ["pallet_1", "pallet_1", "pallet_2"]
    assert [item["sequence"] for item in matches] == ["1", "2", "3"]
    assert [item["stacker"] for item in matches] == ["1", "1", "1"]
    assert [item["cell"] for item in matches] == ["1", "2", "2"]
    assert count_prefix_pallets(html, prefix="910") == 3


def test_reclaim_boxes_excel_download_has_filter_and_numeric_pallet_sort(client, monkeypatch):
    """Printer export returns a titled workbook with filterable, ascending pallet rows."""
    html = """
    <table>
      <thead><tr><th>Cell ID</th><th>Stacker</th><th>Cell</th><th>Height</th><th>Status</th><th>Pallet 1</th><th>Pallet 2</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>2</td><td>30</td><td>52</td><td>Active</td><td>9101010</td><td></td></tr>
        <tr><td>2</td><td>1</td><td>8</td><td>52</td><td>Active</td><td>9102</td><td>91010</td></tr>
      </tbody>
    </table>
    """

    class FakeAsyncClient:
        """Provide CFP source HTML without making an external request."""

        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return SimpleNamespace(
                text=html,
                raise_for_status=lambda: None,
            )

    monkeypatch.setattr(warehouse.httpx, "AsyncClient", FakeAsyncClient)
    response = client.get("/api/warehouse/reclaim-boxes/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="reclaim_boxes_in_cma_'
    )
    workbook = load_workbook(BytesIO(response.content), data_only=True)
    sheet = workbook["Reclaim Boxes"]
    assert sheet["A1"].value == "Reclaim Boxes in CMA"
    assert [sheet.cell(2, column).value for column in range(1, 7)] == [
        "Sequence",
        "Pallet Number",
        "Stacker",
        "Cell",
        "Pallet Slot",
        "Location",
    ]
    assert [sheet.cell(row, 2).value for row in range(3, 6)] == [
        "9102",
        "91010",
        "9101010",
    ]
    assert sheet.auto_filter.ref == "A2:F5"
    assert sheet.freeze_panes == "A3"
    assert sheet["B3"].number_format == "@"
    assert "A1:F1" in {str(merged) for merged in sheet.merged_cells.ranges}
    workbook.close()


@pytest.mark.parametrize(
    ("export_key", "title", "sheet_name", "prefix", "filename_slug"),
    [
        (
            "color-rolls-scrap",
            "Color Rolls Scrap in CMA",
            "Color Rolls Scrap",
            "99",
            "color_rolls_scrap_in_cma",
        ),
        (
            "sheet-81-3313-080",
            "Sheet 81-3313-080",
            "Sheet 81-3313-080",
            "980200",
            "sheet_81-3313-080",
        ),
        (
            "sheet-81-331-081",
            "Sheet 81-331-081",
            "Sheet 81-331-081",
            "980201",
            "sheet_81-331-081",
        ),
    ],
)
def test_warehouse_pallet_excel_exports_use_the_configured_card_data(
    client, monkeypatch, export_key, title, sheet_name, prefix, filename_slug
):
    """Each Warehouse printer card produces a titled workbook for its own prefix."""
    html = f"""
    <table>
      <thead><tr><th>Cell ID</th><th>Stacker</th><th>Cell</th><th>Height</th><th>Status</th><th>Pallet 1</th><th>Pallet 2</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>2</td><td>30</td><td>52</td><td>Active</td><td>{prefix}100</td><td></td></tr>
        <tr><td>2</td><td>1</td><td>8</td><td>52</td><td>Active</td><td>{prefix}2</td><td></td></tr>
      </tbody>
    </table>
    """

    class FakeAsyncClient:
        """Provide CFP fixture data without an external request."""

        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return SimpleNamespace(text=html, raise_for_status=lambda: None)

    monkeypatch.setattr(warehouse.httpx, "AsyncClient", FakeAsyncClient)
    response = client.get(f"/api/warehouse/{export_key}/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"].startswith(
        f'attachment; filename="{filename_slug}_'
    )
    workbook = load_workbook(BytesIO(response.content), data_only=True)
    sheet = workbook[sheet_name]
    assert sheet["A1"].value == title
    assert [sheet.cell(row, 2).value for row in (3, 4)] == [f"{prefix}2", f"{prefix}100"]
    assert sheet.auto_filter.ref == "A2:F4"
    assert sheet.freeze_panes == "A3"
    workbook.close()
