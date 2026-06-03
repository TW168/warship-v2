"""Maintenance routes for shipment-size workload decomposition analytics."""

from __future__ import annotations

import datetime
from collections import defaultdict

import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import connect_to_database
from schemas.shipment_size_impact import (
    ShipmentSizeImpactLatestSummary,
    ShipmentSizeImpactMetadata,
    ShipmentSizeImpactMonth,
    ShipmentSizeImpactResponse,
    ShipmentSizeImpactSeries,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

# Stable endpoint names make this feature easy to move to another router later.
_PAGE_ENDPOINT_NAME = "shipment_size_impact_page"
_API_ENDPOINT_NAME = "shipment_size_impact_api"


@router.get(
    "/shipment-size-impact",
    response_class=HTMLResponse,
    name=_PAGE_ENDPOINT_NAME,
    summary="Shipment size and workload impact",
    description=(
        "Renders a decomposition dashboard that explains monthly volume as "
        "load count x average lbs per load and quantifies extra load pressure "
        "caused by smaller shipment size."
    ),
)
async def shipment_size_impact_page(request: Request) -> HTMLResponse:
    """Render the shipment-size workload decomposition page."""
    today = datetime.date.today().isoformat()
    return templates.TemplateResponse(
        "maintenance/shipment_size_impact.html",
        {
            "request": request,
            "active_page": "shipment_size_impact",
            "api_path": str(request.url_for(_API_ENDPOINT_NAME)),
            "default_date_from": "2023-01-01",
            "default_date_to": today,
        },
    )


@router.get(
    "/volume-decomposition",
    include_in_schema=False,
)
async def shipment_size_impact_legacy_alias(request: Request) -> RedirectResponse:
    """Temporary alias to keep old links working if the page slug changes again."""
    return RedirectResponse(url=str(request.url_for(_PAGE_ENDPOINT_NAME)), status_code=307)


@router.get(
    "/api/shipment-size-impact",
    response_model=ShipmentSizeImpactResponse,
    name=_API_ENDPOINT_NAME,
    summary="Shipment size and workload decomposition",
    description=(
        "Calls sp_bl_lbs_cnt_carrier and returns monthly decomposition metrics: "
        "total lbs, load count, avg lbs per load, loads per million lbs, and "
        "year-over-year effects split into load effect vs shipment-size effect."
    ),
)
async def shipment_size_impact_api(
    site: str = Query(default="AMJK", description="Site code, e.g. AMJK"),
    product_group: str = Query(default="SW", description="Product group, e.g. SW"),
    date_from: str = Query(default="2023-01-01", description="Inclusive start date (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Inclusive end date (YYYY-MM-DD). Defaults to today."),
    exclude_carriers: bool = Query(default=False, description="Exclude SAIA-IP and CWF-IP carriers"),
) -> JSONResponse:
    """Return monthly decomposition metrics for shipment-size workload analysis."""
    try:
        start_date = datetime.date.fromisoformat(date_from.strip())
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": f"Invalid date_from: {exc}"})

    end_date_value = date_to or datetime.date.today().isoformat()
    try:
        end_date = datetime.date.fromisoformat(end_date_value.strip())
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": f"Invalid date_to: {exc}"})

    if start_date > end_date:
        return JSONResponse(status_code=400, content={"error": "date_from must be <= date_to"})

    try:
        with _engine.connect() as conn:
            dbapi_conn = conn.connection
            cursor = dbapi_conn.cursor(dictionary=True)

            try:
                cursor.callproc(
                    "sp_bl_lbs_cnt_carrier",
                    [
                        start_date.isoformat(),
                        end_date.isoformat(),
                        site,
                        product_group,
                    ],
                )

                sp_rows: list[dict] = []
                for result_set in cursor.stored_results():
                    sp_rows.extend(result_set.fetchall())
            finally:
                cursor.close()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    if not sp_rows:
        return JSONResponse(status_code=404, content={"error": "No data found for specified parameters"})

    df = pd.DataFrame(sp_rows)
    if "Truck_Appointment_Date" not in df.columns:
        return JSONResponse(status_code=500, content={"error": "Missing Truck_Appointment_Date column"})

    records_after_carrier_filter = len(sp_rows)
    if exclude_carriers:
        excluded_carrier_list = ["SAIA-IP", "CWF-IP"]
        carrier_col = None
        for col in df.columns:
            if "carrier" in col.lower():
                carrier_col = col
                break

        if carrier_col:
            df = df[~df[carrier_col].isin(excluded_carrier_list)]
            records_after_carrier_filter = len(df)
    else:
        excluded_carrier_list = []

    df["Truck_Appointment_Date"] = pd.to_datetime(df["Truck_Appointment_Date"], errors="coerce")
    df = df.dropna(subset=["Truck_Appointment_Date"])

    df["year"] = df["Truck_Appointment_Date"].dt.year
    df["month"] = df["Truck_Appointment_Date"].dt.month

    df["pick_weight"] = pd.to_numeric(df.get("pick_weight", 0), errors="coerce").fillna(0.0)

    monthly_data = (
        df.groupby(["year", "month"])
        .agg({"pick_weight": "sum", "BL_Number": "nunique"})
        .reset_index()
        .rename(columns={"BL_Number": "load_count", "pick_weight": "total_weight_lbs"})
    )

    monthly_data["avg_lbs_per_load"] = monthly_data.apply(
        lambda row: (row["total_weight_lbs"] / row["load_count"]) if row["load_count"] else 0.0,
        axis=1,
    )
    monthly_data["loads_per_million_lbs"] = monthly_data.apply(
        lambda row: (row["load_count"] / (row["total_weight_lbs"] / 1_000_000)) if row["total_weight_lbs"] else 0.0,
        axis=1,
    )

    lookup = {
        (int(row.year), int(row.month)): row
        for row in monthly_data.itertuples(index=False)
    }

    table_rows: list[ShipmentSizeImpactMonth] = []
    for row in monthly_data.sort_values(["year", "month"]).itertuples(index=False):
        year = int(row.year)
        month = int(row.month)
        weight = float(row.total_weight_lbs)
        loads = int(row.load_count)
        avg_size = float(row.avg_lbs_per_load)

        prior = lookup.get((year - 1, month))

        prior_weight = float(prior.total_weight_lbs) if prior is not None else None
        prior_loads = int(prior.load_count) if prior is not None else None
        prior_avg = float(prior.avg_lbs_per_load) if prior is not None else None

        if prior is not None:
            weight_delta = weight - prior_weight
            load_delta = loads - prior_loads
            avg_delta = avg_size - prior_avg

            load_effect = load_delta * ((prior_avg + avg_size) / 2)
            size_effect = avg_delta * ((prior_loads + loads) / 2)
            explained_delta = load_effect + size_effect
            unexplained_delta = weight_delta - explained_delta

            extra_loads = None
            if avg_size > 0 and prior_avg > 0:
                extra_loads = weight * ((1 / avg_size) - (1 / prior_avg))
        else:
            weight_delta = None
            load_delta = None
            avg_delta = None
            load_effect = None
            size_effect = None
            explained_delta = None
            unexplained_delta = None
            extra_loads = None

        table_rows.append(
            ShipmentSizeImpactMonth(
                year=year,
                month=month,
                total_weight_lbs=round(weight, 0),
                load_count=loads,
                avg_lbs_per_load=round(avg_size, 2),
                loads_per_million_lbs=round(float(row.loads_per_million_lbs), 2),
                prior_year_weight_lbs=round(prior_weight, 0) if prior_weight is not None else None,
                prior_year_load_count=prior_loads,
                prior_year_avg_lbs_per_load=round(prior_avg, 2) if prior_avg is not None else None,
                weight_delta_lbs=round(weight_delta, 0) if weight_delta is not None else None,
                load_delta=load_delta,
                avg_lbs_per_load_delta=round(avg_delta, 2) if avg_delta is not None else None,
                load_effect_lbs=round(load_effect, 0) if load_effect is not None else None,
                shipment_size_effect_lbs=round(size_effect, 0) if size_effect is not None else None,
                explained_delta_lbs=round(explained_delta, 0) if explained_delta is not None else None,
                unexplained_delta_lbs=round(unexplained_delta, 2) if unexplained_delta is not None else None,
                extra_loads_due_to_smaller_shipments=round(extra_loads, 2) if extra_loads is not None else None,
            )
        )

    by_year: dict[int, list[ShipmentSizeImpactMonth]] = defaultdict(list)
    for metric in table_rows:
        by_year[metric.year].append(metric)

    series = [
        ShipmentSizeImpactSeries(
            year=year,
            site=site,
            product_group=product_group,
            data=sorted(metrics, key=lambda item: item.month),
        )
        for year, metrics in sorted(by_year.items())
    ]

    comparable_months = [
        row for row in table_rows
        if row.prior_year_avg_lbs_per_load is not None
    ]
    latest_summary = ShipmentSizeImpactLatestSummary()
    if comparable_months:
        latest = max(comparable_months, key=lambda item: (item.year, item.month))
        latest_summary = ShipmentSizeImpactLatestSummary(
            year=latest.year,
            month=latest.month,
            total_weight_lbs=latest.total_weight_lbs,
            load_count=latest.load_count,
            avg_lbs_per_load=latest.avg_lbs_per_load,
            prior_year_avg_lbs_per_load=latest.prior_year_avg_lbs_per_load,
            extra_loads_due_to_smaller_shipments=latest.extra_loads_due_to_smaller_shipments,
            load_effect_lbs=latest.load_effect_lbs,
            shipment_size_effect_lbs=latest.shipment_size_effect_lbs,
        )

    payload = ShipmentSizeImpactResponse(
        series=series,
        monthly_table=table_rows,
        latest_summary=latest_summary,
        metadata=ShipmentSizeImpactMetadata(
            site=site,
            product_group=product_group,
            date_range=f"{start_date.isoformat()} to {end_date.isoformat()}",
            exclude_carriers=exclude_carriers,
            excluded_carriers=excluded_carrier_list,
            total_records_original=len(sp_rows),
            total_records_after_filter=records_after_carrier_filter,
            total_records_final=len(df),
            metric_formula="Total shipped lbs = load_count x avg_lbs_per_load",
        ),
    )

    return JSONResponse(content=payload.model_dump())
