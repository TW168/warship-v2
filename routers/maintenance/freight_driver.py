"""Maintenance routes for freight ¢/lb root-cause drill-down analytics.

Answers "why is this product's freight ¢/lb rising?" by decomposing the
year-over-year blended ¢/lb change into carrier-mix and carrier-rate effects
(symmetric midpoint shift-share), with shipment-size context and outlier loads.
A companion endpoint ranks the products whose ¢/lb increased the most.

Blended ¢/lb uses "Method A" (weighted average of Unit_Freight by Pick_Weight),
matching routers/maintenance/freight_audit.py.

Lane/destination is intentionally out of scope for v1: sp_get_all_shipped_product
does not expose ship-to fields. See metadata.method.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.freight_driver import (
    CarrierBreakdownRow,
    DestinationBreakdownRow,
    DestinationDecomposition,
    FreightDriverDecomposition,
    FreightDriverMetadata,
    FreightDriverMonth,
    FreightDriverResponse,
    FreightDriverSeries,
    FreightRisersMetadata,
    FreightRisersResponse,
    MarketContext,
    OutlierBL,
    PrimaryDriverVerdict,
    RiserRow,
    ShipmentSizeContext,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
_engine = connect_to_database()

# Stable endpoint names so templates can use request.url_for(...) instead of
# hardcoding paths (paths resolve under the parent /maintenance prefix).
_PAGE_ENDPOINT_NAME = "freight_driver_page"
_API_ENDPOINT_NAME = "freight_driver_api"
_RISERS_ENDPOINT_NAME = "freight_risers_api"

_METHOD_NOTE = (
    "Blended ¢/lb = SUM(Unit_Freight × Pick_Weight) / SUM(Pick_Weight) (Method A). "
    "YoY change split via symmetric midpoint shift-share: "
    "mix_effect = Σ Δshare × (rate_cur+rate_prior)/2; "
    "rate_effect = Σ Δrate × (share_cur+share_prior)/2. "
    "A carrier present in only one period is treated as mix (its missing-period rate "
    "is set equal to the present-period rate). Destination/lane is not modelled in v1 "
    "(ship-to fields are not exposed by sp_get_all_shipped_product)."
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_dates(date_from: str, date_to: str | None):
    """Validate the date window. Returns (start, end) or raises ValueError."""
    start = datetime.date.fromisoformat(date_from.strip())
    end_value = date_to or datetime.date.today().isoformat()
    end = datetime.date.fromisoformat(end_value.strip())
    if start > end:
        raise ValueError("date_from must be <= date_to")
    return start, end


def _fetch_rows(site: str, product_group: str, start: datetime.date, end: datetime.date) -> list[dict]:
    """Call sp_get_all_shipped_product and return normalized lowercase-keyed rows.

    Uses the raw mysql-connector cursor directly (same pattern as
    routers/shipping.py) because SQLAlchemy text("CALL ...") does not reliably
    handle stored-procedure result sets with this driver.
    """
    rows: list[dict] = []
    with _engine.connect() as conn:
        dbapi_conn = conn.connection
        cursor = dbapi_conn.cursor(dictionary=True)
        try:
            cursor.callproc(
                "sp_get_all_shipped_product",
                [str(site), str(product_group), start.isoformat(), end.isoformat()],
            )
            for result_set in cursor.stored_results():
                for row in result_set.fetchall():
                    appt = row.get("Truck_Appointment_Date")
                    rows.append({
                        "bl_number": row.get("BL_Number"),
                        "date": appt if isinstance(appt, datetime.date) else None,
                        "product_code": row.get("Product_Code"),
                        "unit_freight": (
                            float(row["Unit_Freight"]) if row.get("Unit_Freight") is not None else None
                        ),
                        "carrier_id": row.get("Carrier_ID"),
                        "pick_weight": (
                            float(row["pick_weight"]) if row.get("pick_weight") is not None else None
                        ),
                    })
        finally:
            cursor.close()
    return rows


def _blended_cplb(rows: list[dict]) -> float | None:
    """Method A weighted-average ¢/lb over rows with usable freight + weight."""
    num = 0.0
    den = 0.0
    for r in rows:
        uf, pw = r["unit_freight"], r["pick_weight"]
        if uf is not None and pw:
            num += uf * pw
            den += pw
    return (num / den) if den else None


def _total_weight(rows: list[dict]) -> float:
    """Sum of usable pick weight."""
    return sum(r["pick_weight"] for r in rows if r["pick_weight"])


def _window(rows: list[dict], year: int, max_month: int) -> list[dict]:
    """Rows in the given year with month <= max_month (valid dates only)."""
    return [r for r in rows if r["date"] and r["date"].year == year and r["date"].month <= max_month]


def _current_prior_split(rows: list[dict]):
    """Return (current_year, max_month, current_rows, prior_rows).

    Current = Jan..(latest month present) of the most recent year with data;
    prior = the same Jan..month window one year earlier.
    """
    dated = [r for r in rows if r["date"]]
    if not dated:
        return None, None, [], []
    cur_year = max(r["date"].year for r in dated)
    max_month = max(r["date"].month for r in dated if r["date"].year == cur_year)
    return cur_year, max_month, _window(rows, cur_year, max_month), _window(rows, cur_year - 1, max_month)


def _dim_aggregates(rows: list[dict], key: str) -> dict[str, dict]:
    """Per-key (carrier or destination) weight and Method-A ¢/lb for one window."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r.get(key) or "(unknown)"].append(r)
    out: dict[str, dict] = {}
    for k, krows in by_key.items():
        out[k] = {"weight": _total_weight(krows), "cplb": _blended_cplb(krows)}
    return out


def _shift_share(cur_agg: dict[str, dict], prior_agg: dict[str, dict],
                 cur_total: float, prior_total: float):
    """Symmetric midpoint shift-share over one dimension (carrier or destination).

    Returns (per_key_rows, mix_total, rate_total). Each per-key row carries its
    shares, rates, weights, and its mix/rate contribution. A key present in only
    one period is treated as pure mix (its missing-period rate is set equal to
    the present-period rate) so it does not create a phantom rate spike.
    """
    rows = []
    mix_total = 0.0
    rate_total = 0.0
    for k in sorted(set(cur_agg) | set(prior_agg)):
        cw = cur_agg.get(k, {}).get("weight", 0.0)
        pw = prior_agg.get(k, {}).get("weight", 0.0)
        c_rate = cur_agg.get(k, {}).get("cplb")
        p_rate = prior_agg.get(k, {}).get("cplb")
        cur_share = (cw / cur_total) if cur_total else 0.0
        prior_share = (pw / prior_total) if prior_total else 0.0
        eff_cur = c_rate if c_rate is not None else p_rate
        eff_prior = p_rate if p_rate is not None else c_rate
        if eff_cur is None or eff_prior is None:
            mix_c = rate_c = 0.0
        else:
            mix_c = (cur_share - prior_share) * (eff_cur + eff_prior) / 2.0
            rate_c = (eff_cur - eff_prior) * (cur_share + prior_share) / 2.0
        mix_total += mix_c
        rate_total += rate_c
        rows.append({
            "key": k, "cur_share": cur_share, "prior_share": prior_share,
            "cur_cplb": c_rate, "prior_cplb": p_rate, "cur_weight": cw, "prior_weight": pw,
            "mix_effect": mix_c, "rate_effect": rate_c,
        })
    rows.sort(key=lambda r: abs(r["mix_effect"] + r["rate_effect"]), reverse=True)
    return rows, mix_total, rate_total


def _fetch_ship_to(site: str, product_group: str, start: datetime.date,
                   end: datetime.date, product_code: str) -> dict[str, str]:
    """Map BL_Number → ship-to State for one product (latest snapshot per BL).

    Read-only query against ipg_ez (the SP does not expose ship-to fields). Uses
    the same latest-snapshot dedup as routers/maintenance/freight_audit.py.
    Returns {} on any failure so the destination lens degrades gracefully.
    """
    sql = text(
        """
        SELECT s.BL_Number AS bl, s.State AS state
        FROM ipg_ez s
        WHERE s.Site = :site
          AND s.Product_Group = :pg
          AND s.Product_Code = :pc
          AND s.Truck_Appointment_Date BETWEEN :df AND :dt
          AND NOT EXISTS (
              SELECT 1 FROM ipg_ez n
              WHERE n.BL_Number = s.BL_Number
                AND (n.snap_ts > s.snap_ts
                     OR (n.snap_ts = s.snap_ts AND n.file_name > s.file_name))
          )
        """
    )
    out: dict[str, str] = {}
    try:
        with _engine.connect() as conn:
            for row in conn.execute(sql, {
                "site": site, "pg": product_group, "pc": product_code,
                "df": start.isoformat(), "dt": end.isoformat(),
            }):
                if row.bl is not None:
                    out[str(row.bl)] = (row.state or "(unknown)")
    except Exception:
        return {}
    return out


def _period_label(year: int | None, max_month: int | None) -> str:
    """Human label like '2026 Jan–May' for a YTD-style window."""
    if not year or not max_month:
        return "n/a"
    month_abbr = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{year} Jan–{month_abbr[max_month]}"


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get(
    "/freight-driver",
    response_class=HTMLResponse,
    name=_PAGE_ENDPOINT_NAME,
    summary="Freight ¢/lb root-cause drill-down",
    description=(
        "Lists the products whose freight ¢/lb rose the most year-over-year and, "
        "for any chosen product, decomposes the increase into carrier-mix and "
        "carrier-rate effects with shipment-size context and outlier loads."
    ),
)
async def freight_driver_page(
    request: Request,
    site: str = Query(default="AMJK"),
    product_group: str = Query(default="SW"),
    product_code: str | None = Query(default=None),
) -> HTMLResponse:
    """Render the freight-driver analysis page (optionally deep-linked to a product)."""
    today = datetime.date.today().isoformat()
    return templates.TemplateResponse(
        "maintenance/freight_driver.html",
        {
            "request": request,
            "active_page": "freight_driver",
            "api_path": str(request.url_for(_API_ENDPOINT_NAME)),
            "risers_path": str(request.url_for(_RISERS_ENDPOINT_NAME)),
            "shipped_products_path": "/api/shipping/shipped-products",
            "default_date_from": "2023-01-01",
            "default_date_to": today,
            "preset_site": site,
            "preset_product_group": product_group,
            "preset_product_code": product_code or "",
        },
    )


# ---------------------------------------------------------------------------
# API — single-product decomposition
# ---------------------------------------------------------------------------

@router.get(
    "/api/freight-driver",
    response_model=FreightDriverResponse,
    name=_API_ENDPOINT_NAME,
    summary="Freight ¢/lb driver decomposition for one product",
    description=(
        "Decomposes a product's YoY blended ¢/lb change into carrier-mix and "
        "carrier-rate effects, with a monthly trend, per-carrier table, outlier "
        "loads, shipment-size context, and a rule-based primary-driver verdict."
    ),
)
async def freight_driver_api(
    site: str = Query(default="AMJK", description="Site code, e.g. AMJK"),
    product_group: str = Query(default="SW", description="Product group, e.g. SW"),
    product_code: str = Query(..., description="Product code to analyze"),
    date_from: str = Query(default="2023-01-01", description="Inclusive start (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Inclusive end (YYYY-MM-DD). Defaults to today."),
    top_outliers: int = Query(default=10, ge=1, le=50, description="Number of costliest loads to return"),
) -> JSONResponse:
    """Return the freight ¢/lb driver decomposition for a single product."""
    try:
        start, end = _parse_dates(date_from, date_to)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    try:
        all_rows = _fetch_rows(site, product_group, start, end)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    rows = [r for r in all_rows if r["product_code"] == product_code]
    if not rows:
        return JSONResponse(
            status_code=404,
            content={"error": f"No data for product_code '{product_code}'"},
        )

    # ── Monthly series grouped by year ──────────────────────────────────────
    monthly: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        if r["date"]:
            monthly[(r["date"].year, r["date"].month)].append(r)

    by_year: dict[int, list[FreightDriverMonth]] = defaultdict(list)
    for (yr, mo), mrows in sorted(monthly.items()):
        wt = _total_weight(mrows)
        loads = len({r["bl_number"] for r in mrows})
        by_year[yr].append(FreightDriverMonth(
            year=yr, month=mo, ym=f"{yr}-{mo:02d}",
            blended_cplb=round(_blended_cplb(mrows) or 0.0, 3),
            total_weight_lbs=round(wt, 0),
            load_count=loads,
            avg_lbs_per_load=round(wt / loads, 1) if loads else 0.0,
        ))
    series = [
        FreightDriverSeries(year=yr, data=sorted(months, key=lambda m: m.month))
        for yr, months in sorted(by_year.items())
    ]

    # ── Current vs prior windows ────────────────────────────────────────────
    cur_year, max_month, cur_rows, prior_rows = _current_prior_split(rows)
    cur_period = _period_label(cur_year, max_month)
    prior_period = _period_label(cur_year - 1 if cur_year else None, max_month)

    cur_blended = _blended_cplb(cur_rows) or 0.0
    prior_blended = _blended_cplb(prior_rows)
    cur_total_w = _total_weight(cur_rows)
    prior_total_w = _total_weight(prior_rows)

    total_delta = cur_blended - (prior_blended if prior_blended is not None else cur_blended)

    # ── Carrier lens: symmetric midpoint shift-share ────────────────────────
    car_rows, mix_total, rate_total = _shift_share(
        _dim_aggregates(cur_rows, "carrier_id"),
        _dim_aggregates(prior_rows, "carrier_id"),
        cur_total_w, prior_total_w,
    )
    carrier_table = [
        CarrierBreakdownRow(
            carrier_id=r["key"],
            cur_share=round(r["cur_share"], 4),
            prior_share=round(r["prior_share"], 4),
            share_delta=round(r["cur_share"] - r["prior_share"], 4),
            cur_cplb=round(r["cur_cplb"], 3) if r["cur_cplb"] is not None else None,
            prior_cplb=round(r["prior_cplb"], 3) if r["prior_cplb"] is not None else None,
            rate_delta=(round(r["cur_cplb"] - r["prior_cplb"], 3)
                        if (r["cur_cplb"] is not None and r["prior_cplb"] is not None) else None),
            cur_weight=round(r["cur_weight"], 0),
            prior_weight=round(r["prior_weight"], 0),
            mix_effect=round(r["mix_effect"], 3),
            rate_effect=round(r["rate_effect"], 3),
        )
        for r in car_rows
    ]

    explained = mix_total + rate_total
    decomposition = FreightDriverDecomposition(
        prior_blended_cplb=round(prior_blended, 3) if prior_blended is not None else 0.0,
        current_blended_cplb=round(cur_blended, 3),
        total_delta=round(total_delta, 3),
        mix_effect=round(mix_total, 3),
        rate_effect=round(rate_total, 3),
        explained=round(explained, 3),
        residual=round(total_delta - explained, 3),
    )

    # ── Destination lens (ship-to state) — parallel shift-share ─────────────
    ship_to = _fetch_ship_to(site, product_group, start, end, product_code)
    for r in rows:
        r["state"] = ship_to.get(str(r["bl_number"]), "(unknown)")
    dest_available = bool(ship_to)

    dest_rows, dmix_total, drate_total = _shift_share(
        _dim_aggregates(cur_rows, "state"),
        _dim_aggregates(prior_rows, "state"),
        cur_total_w, prior_total_w,
    )
    destination_table = [
        DestinationBreakdownRow(
            destination=r["key"],
            cur_share=round(r["cur_share"], 4),
            prior_share=round(r["prior_share"], 4),
            share_delta=round(r["cur_share"] - r["prior_share"], 4),
            cur_cplb=round(r["cur_cplb"], 3) if r["cur_cplb"] is not None else None,
            prior_cplb=round(r["prior_cplb"], 3) if r["prior_cplb"] is not None else None,
            rate_delta=(round(r["cur_cplb"] - r["prior_cplb"], 3)
                        if (r["cur_cplb"] is not None and r["prior_cplb"] is not None) else None),
            cur_weight=round(r["cur_weight"], 0),
            prior_weight=round(r["prior_weight"], 0),
            mix_effect=round(r["mix_effect"], 3),
            rate_effect=round(r["rate_effect"], 3),
        )
        for r in dest_rows
    ] if dest_available else []
    dest_explained = dmix_total + drate_total
    destination_decomposition = DestinationDecomposition(
        mix_effect=round(dmix_total, 3) if dest_available else 0.0,
        rate_effect=round(drate_total, 3) if dest_available else 0.0,
        explained=round(dest_explained, 3) if dest_available else 0.0,
        residual=round(total_delta - dest_explained, 3) if dest_available else 0.0,
        available=dest_available,
    )

    # ── LMI macro freight-price context ─────────────────────────────────────
    market_context = _build_market_context()

    # ── Shipment-size context ───────────────────────────────────────────────
    cur_loads = len({r["bl_number"] for r in cur_rows})
    prior_loads = len({r["bl_number"] for r in prior_rows})
    cur_avg = (cur_total_w / cur_loads) if cur_loads else 0.0
    prior_avg = (prior_total_w / prior_loads) if prior_loads else 0.0
    size_ctx = ShipmentSizeContext(
        cur_avg_lbs_per_bl=round(cur_avg, 0),
        prior_avg_lbs_per_bl=round(prior_avg, 0),
        avg_lbs_delta=round(cur_avg - prior_avg, 0),
        pct_change=round((cur_avg - prior_avg) / prior_avg * 100, 1) if prior_avg else 0.0,
    )

    # ── Outliers — costliest current-window loads ───────────────────────────
    outlier_rows = sorted(
        [r for r in cur_rows if r["unit_freight"] is not None and r["pick_weight"]],
        key=lambda r: r["unit_freight"], reverse=True,
    )[:top_outliers]
    outliers = [
        OutlierBL(
            bl_number=str(r["bl_number"]),
            truck_appointment_date=r["date"].isoformat() if r["date"] else None,
            carrier_id=r["carrier_id"],
            unit_freight=round(r["unit_freight"], 3),
            pick_weight=round(r["pick_weight"], 0),
        )
        for r in outlier_rows
    ]

    # ── Rule-based verdict (carrier vs destination vs rate, + LMI) ──────────
    verdict = _build_verdict(
        product_code, decomposition, carrier_table, destination_table,
        destination_decomposition, size_ctx, market_context,
        has_prior=prior_total_w > 0,
    )

    payload = FreightDriverResponse(
        series=series,
        decomposition=decomposition,
        carrier_table=carrier_table,
        destination_table=destination_table,
        destination_decomposition=destination_decomposition,
        market_context=market_context,
        outliers=outliers,
        shipment_size_context=size_ctx,
        verdict=verdict,
        metadata=FreightDriverMetadata(
            site=site, product_group=product_group, product_code=product_code,
            current_period=cur_period, prior_period=prior_period,
            date_range=f"{start.isoformat()} to {end.isoformat()}",
            total_rows=len(all_rows), rows_for_product=len(rows),
            method=_METHOD_NOTE,
        ),
    )
    return JSONResponse(content=payload.model_dump())


def _build_market_context() -> MarketContext:
    """Build the LMI macro freight-price context (best-effort, never raises)."""
    try:
        from routers.maintenance.lmi import get_latest_transportation_prices
        tp = get_latest_transportation_prices()
    except Exception:
        tp = None

    if not tp:
        return MarketContext(available=False, interpretation="LMI freight-price data unavailable.")

    val = tp["value"]
    direction = tp["direction"]
    if val >= 60:
        market = f"the freight market is hot (LMI Transportation Prices {val:.1f}, {direction})"
        squeeze = "high"
    elif val >= 50:
        market = f"freight prices are expanding modestly (LMI Transportation Prices {val:.1f}, {direction})"
        squeeze = "modest"
    else:
        market = f"freight prices are contracting market-wide (LMI Transportation Prices {val:.1f}, {direction})"
        squeeze = "low"

    return MarketContext(
        available=True,
        lmi_transportation_prices=val,
        direction=direction,
        month=tp["month"],
        interpretation=f"As of {tp['month']}, {market}.",
        # squeeze level is reflected in the wording; kept implicit in interpretation
    )


def _build_verdict(
    product_code: str,
    dec: FreightDriverDecomposition,
    carriers: list[CarrierBreakdownRow],
    destinations: list[DestinationBreakdownRow],
    dest_dec: DestinationDecomposition,
    size: ShipmentSizeContext,
    market: MarketContext,
    has_prior: bool,
) -> PrimaryDriverVerdict:
    """Conclude the dominant driver across carrier-mix, destination-mix, and rate.

    Carrier and destination are two parallel lenses that each fully explain the
    same total change. We pick the single biggest *mix* explanation (carrier or
    destination); if the carrier-rate effect dwarfs even the best mix lens, the
    rise is a genuine price increase and we bring in the LMI market read.
    """
    if not has_prior:
        return PrimaryDriverVerdict(
            driver="insufficient_data",
            headline="Not enough prior-year history to explain the change.",
            detail="There is no comparable prior-year window for this product, so a "
                   "year-over-year driver decomposition cannot be computed.",
            dominant_carrier_id=None,
        )

    cm, cr = dec.mix_effect, dec.rate_effect          # carrier lens
    dm = dest_dec.mix_effect if dest_dec.available else 0.0  # destination-mix
    abs_cm, abs_cr, abs_dm = abs(cm), abs(cr), abs(dm)

    best_mix_abs = max(abs_cm, abs_dm)
    dominant_carrier = max(carriers, key=lambda c: abs(c.mix_effect + c.rate_effect), default=None)
    dominant_id = dominant_carrier.carrier_id if dominant_carrier else None
    top_dest = destinations[0].destination if destinations else None

    if abs_cr >= 1.5 * best_mix_abs:
        driver = "carrier_rate"
    elif abs_dm > abs_cm:
        driver = "destination_mix"
    elif abs_cm >= 1.5 * abs_cr:
        driver = "carrier_mix"
    else:
        driver = "mixed"

    direction = "up" if dec.total_delta >= 0 else "down"
    delta_abs = abs(dec.total_delta)

    # Causal phrasing follows the SIGN of the dominant effect, so a falling
    # ¢/lb reads "cheaper / charging less" rather than "costlier / more".
    if driver == "carrier_rate":
        verb = "charging more" if cr >= 0 else "charging less"
        lead = f"it is mostly a rate change — the same carriers/lanes {verb} per pound"
        lead += f" (led by {dominant_id})." if dominant_id else "."
    elif driver == "destination_mix":
        where = "costlier" if dm >= 0 else "cheaper"
        lead = f"it is mostly destination mix — more volume shipping to {where} destinations"
        lead += f" (led by {top_dest})." if top_dest else "."
    elif driver == "carrier_mix":
        where = "pricier" if cm >= 0 else "cheaper"
        lead = f"it is mostly carrier mix — volume shifting to {where} carriers"
        lead += f" (led by {dominant_id})." if dominant_id else "."
    else:
        lead = "it is a mix of carrier choice, destination, and rate changes."

    headline = (
        f"{product_code} freight is {direction} {delta_abs:.2f}¢/lb year-over-year "
        f"({dec.prior_blended_cplb:.2f} → {dec.current_blended_cplb:.2f}); {lead}"
    )

    detail = (
        f"By carrier: mix {cm:+.2f}¢/lb, rate {cr:+.2f}¢/lb. "
        + (f"By destination (ship-to state): mix {dest_dec.mix_effect:+.2f}¢/lb, "
           f"rate {dest_dec.rate_effect:+.2f}¢/lb. " if dest_dec.available
           else "Destination breakdown unavailable. ")
    )
    if size.prior_avg_lbs_per_bl and abs(size.pct_change) >= 3:
        verb = "smaller" if size.pct_change < 0 else "larger"
        effect = "lifts" if size.pct_change < 0 else "lowers"
        detail += (
            f"Loads also got {verb} — avg {size.prior_avg_lbs_per_bl:,.0f} → "
            f"{size.cur_avg_lbs_per_bl:,.0f} lbs/BL ({size.pct_change:+.1f}%), which {effect} "
            f"per-pound rates. "
        )

    # LMI macro read — most relevant when the move is rate-driven. The rate
    # change "aligns" with the market when both point the same way (rate up &
    # market hot, or rate down & market soft).
    if market.available and market.lmi_transportation_prices is not None:
        tp = market.lmi_transportation_prices
        mkt = f"LMI Transportation Prices {tp:.1f} ({market.direction}, {market.month})"
        if driver == "carrier_rate":
            market_hot = tp >= 50
            rate_up = cr >= 0
            if rate_up == market_hot:
                detail += (
                    f"This aligns with the freight market ({mkt}) — largely market-driven"
                    + (", so lock in contracts." if rate_up else ", market-wide relief.")
                )
            else:
                detail += (
                    f"This diverges from the freight market ({mkt}) — carrier-specific, "
                    f"worth a rate review."
                )
        else:
            detail += (
                f"Market context: {mkt}; this change is driven more by mix than the market, "
                f"so it is addressable internally."
            )

    return PrimaryDriverVerdict(
        driver=driver, headline=headline, detail=detail, dominant_carrier_id=dominant_id,
    )


# ---------------------------------------------------------------------------
# API — biggest ¢/lb risers ranking
# ---------------------------------------------------------------------------

@router.get(
    "/api/freight-driver/risers",
    response_model=FreightRisersResponse,
    name=_RISERS_ENDPOINT_NAME,
    summary="Products with the biggest YoY ¢/lb increases",
    description=(
        "Ranks products by year-over-year increase in blended ¢/lb (current "
        "Jan..latest-month window vs the same window last year). Tiny products "
        "below min_weight_share of current volume are dropped."
    ),
)
async def freight_risers_api(
    site: str = Query(default="AMJK", description="Site code, e.g. AMJK"),
    product_group: str = Query(default="SW", description="Product group, e.g. SW"),
    date_from: str = Query(default="2023-01-01", description="Inclusive start (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Inclusive end (YYYY-MM-DD). Defaults to today."),
    top_n: int = Query(default=15, ge=1, le=100, description="Number of movers to return"),
    min_weight_share: float = Query(default=0.005, ge=0.0, le=1.0,
                                     description="Drop products below this share of current volume"),
    direction: str = Query(default="increase", description="'increase' (biggest rises) or 'decrease' (biggest drops)"),
) -> JSONResponse:
    """Return the products whose blended ¢/lb moved the most year-over-year.

    direction='increase' ranks the biggest rises; 'decrease' ranks the biggest drops.
    """
    try:
        start, end = _parse_dates(date_from, date_to)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    try:
        all_rows = _fetch_rows(site, product_group, start, end)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    if not all_rows:
        return JSONResponse(status_code=404, content={"error": "No data for specified parameters"})

    cur_year, max_month, cur_rows, prior_rows = _current_prior_split(all_rows)
    cur_period = _period_label(cur_year, max_month)
    prior_period = _period_label(cur_year - 1 if cur_year else None, max_month)

    cur_by_prod: dict[str, list[dict]] = defaultdict(list)
    for r in cur_rows:
        cur_by_prod[r["product_code"]].append(r)
    prior_by_prod: dict[str, list[dict]] = defaultdict(list)
    for r in prior_rows:
        prior_by_prod[r["product_code"]].append(r)

    total_cur_weight = sum(_total_weight(v) for v in cur_by_prod.values())
    min_weight = total_cur_weight * min_weight_share

    risers: list[RiserRow] = []
    for pc, crows in cur_by_prod.items():
        cur_w = _total_weight(crows)
        if cur_w < min_weight:
            continue
        cur_cplb = _blended_cplb(crows)
        if cur_cplb is None:
            continue
        prior_cplb = _blended_cplb(prior_by_prod.get(pc, []))
        delta = (cur_cplb - prior_cplb) if prior_cplb is not None else None
        pct = (delta / prior_cplb * 100) if (delta is not None and prior_cplb) else None
        risers.append(RiserRow(
            product_code=pc,
            cur_cplb=round(cur_cplb, 3),
            prior_cplb=round(prior_cplb, 3) if prior_cplb is not None else None,
            delta_cplb=round(delta, 3) if delta is not None else None,
            pct_change=round(pct, 1) if pct is not None else None,
            cur_weight_lbs=round(cur_w, 0),
            cur_load_count=len({r["bl_number"] for r in crows}),
        ))

    # Products without a comparable prior baseline always sort last.
    if direction == "decrease":
        # Biggest drops first (most negative delta).
        risers.sort(key=lambda r: (r.delta_cplb is None, r.delta_cplb if r.delta_cplb is not None else 0.0))
    else:
        # Biggest rises first.
        risers.sort(key=lambda r: (r.delta_cplb is not None, r.delta_cplb or 0.0), reverse=True)

    payload = FreightRisersResponse(
        risers=risers[:top_n],
        metadata=FreightRisersMetadata(
            site=site, product_group=product_group,
            current_period=cur_period, prior_period=prior_period,
            products_considered=len(cur_by_prod),
            direction=direction,
        ),
    )
    return JSONResponse(content=payload.model_dump())
