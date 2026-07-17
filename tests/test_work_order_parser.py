"""Tests for CFP extrusion production ticket workbook parsing."""

from pathlib import Path

from utils.work_order_json_parser import parse_work_order_workbook


def test_parse_work_order_workbook_emits_nested_ticket_schema() -> None:
    """Parser should emit the requested nested ticket JSON shape from sample workbook."""
    workbook_path = Path("raw_data/BE01_07152026_D.xlsx")

    parsed, skipped = parse_work_order_workbook(workbook_path)

    assert len(parsed) == 2
    assert len(skipped) == 1

    sample = next(item["document"] for item in parsed if item["sheet_name"] == "EHY063-EHY390")
    ticket = sample["ticket"]

    assert ticket["line"] == "BE01"
    assert ticket["prod_date"] == "2026-07-15"
    assert ticket["ewo"] == "EHY063"
    assert ticket["shift"] == "D"
    assert ticket["crew"] == "D"
    assert ticket["prod_time"] == 445
    assert ticket["operator"] == "KUE NOE POO"

    charting = ticket["charting"][0]
    assert charting["chart"] == "0167000002"
    assert charting["film_type"] == "EHY063"
    assert charting["formula"] == "EHY390"
    assert charting["pack_code"] == "VS2X"
    assert charting["width_in"] == 20
    assert charting["length_ft"] == 5000
    assert charting["prod_weight_lbs"] == 7560
    assert charting["op_test_weight_lbs"] == 26
    assert charting["qc_scrap_lbs"] == 55
    assert charting["total_scrap_lbs"] == 55
    assert charting["downtime_min"] == 35
    assert charting["yield_pct"] == 99.28
    assert charting["weight_to_next_lbs"] == 0

    assert ticket["downtime"] == [{"code": "1A", "time_min": 35}]
    assert len(ticket["pallets"]) == 6
    assert ticket["pallets"][0]["order_nbr"] == "RW26521073"
    assert ticket["pallets"][0]["roll_nbr"] == "RW26521073"
    assert ticket["pallets"][0]["wgt_lbs"] == 1260
    assert ticket["material_usage"]["extruder"][0]["hopper"] == "LL264"
    assert ticket["material_usage"]["extruder"][0]["input_lbs"] == 5064
    assert ticket["material_usage"]["extruder"][0]["std_pct"] is None
    assert len(ticket["material_usage"]["ext_b"]) == 6
    assert ticket["material_usage"]["ext_b"][0]["hopper"] == 1
    assert ticket["comments"] is None