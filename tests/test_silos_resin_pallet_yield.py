"""Tests for the rolling resin-per-pallet yield endpoint and its series builder."""

from fastapi.testclient import TestClient

from main import app
from routers.maintenance.silos.api import _build_resin_pallet_yield_series


client = TestClient(app)


def _rows(*pairs):
    """Build ascending daily rows from (resin_lbs, pallets_in) pairs."""
    return [
        {"date": f"2026-08-{index + 1:02d}", "resin_lbs": resin, "pallets_in": pallets}
        for index, (resin, pallets) in enumerate(pairs)
    ]


def test_rolling_yield_is_ratio_of_sums_not_mean_of_ratios():
    """The window must divide summed resin by summed pallets.

    Daily ratios here are 1000 and 100; their mean would be 550. The correct
    ratio-of-sums is 1100 lbs / 110 pallets = 10 lbs per pallet.
    """
    series = _build_resin_pallet_yield_series(_rows((1000, 1), (100, 109)), window=2)

    assert series[-1]["rolling_yield"] == 10.0
    assert series[-1]["rolling_resin_lbs"] == 1100
    assert series[-1]["rolling_pallets_in"] == 110


def test_rolling_window_only_looks_backwards():
    """Each row's window covers itself and the prior days, never future days."""
    series = _build_resin_pallet_yield_series(_rows((100, 10), (300, 10), (500, 10)), window=2)

    assert series[0]["rolling_yield"] == 10.0  # 100/10, window still filling
    assert series[1]["rolling_yield"] == 20.0  # (100+300)/20
    assert series[2]["rolling_yield"] == 40.0  # (300+500)/20


def test_incomplete_window_is_flagged():
    """Rows that do not yet have a full trailing window are marked incomplete."""
    series = _build_resin_pallet_yield_series(_rows((100, 10), (200, 10), (300, 10)), window=3)

    assert [row["rolling_complete"] for row in series] == [False, False, True]


def test_zero_pallet_days_yield_none_instead_of_dividing_by_zero():
    """A day with no pallets produced must not raise or emit an infinite ratio."""
    series = _build_resin_pallet_yield_series(_rows((5000, 0)), window=1)

    assert series[0]["daily_yield"] is None
    assert series[0]["rolling_yield"] is None


def test_keep_days_trims_seed_rows_from_the_front():
    """Extra leading history used to seed the window is not returned to the caller."""
    series = _build_resin_pallet_yield_series(
        _rows((100, 10), (200, 10), (300, 10), (400, 10)), window=2, keep_days=2
    )

    assert len(series) == 2
    assert series[0]["date"] == "2026-08-03"
    assert all(row["rolling_complete"] for row in series)


def test_resin_pallet_yield_endpoint_returns_expected_shape():
    response = client.get("/maintenance/api/silos/resin-pallet-yield?days=14&window=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"] == 7
    assert isinstance(payload["data"], list)

    if payload["data"]:
        row = payload["data"][0]
        for field in (
            "date",
            "resin_lbs",
            "pallets_in",
            "daily_yield",
            "rolling_yield",
            "rolling_complete",
        ):
            assert field in row


def test_resin_pallet_yield_endpoint_rejects_out_of_range_window():
    """The window is bounded so a caller cannot request an unusable smoothing size."""
    assert client.get("/maintenance/api/silos/resin-pallet-yield?window=0").status_code == 422
    assert client.get("/maintenance/api/silos/resin-pallet-yield?window=99").status_code == 422
