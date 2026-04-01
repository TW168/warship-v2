"""
Product Forecast Engine

Calls sp_get_all_shipped_product and computes per-product:
- Trend direction (INCREASE / DECREASE / STABLE)
- Momentum (6-month recent avg vs prior 6-month avg)
- Linear regression slope, R-squared, and next-month forecast
"""

from collections import defaultdict
from datetime import date, datetime

from database import connect_to_database


def _as_datetime(value):
    """Normalize DB date values (date/datetime/ISO string) to datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _linreg(ys):
    """Simple linear regression on index vs values. Returns (slope, r_squared)."""
    n = len(ys)
    if n < 2:
        return 0.0, 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    r2 = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0
    return slope, r2


def compute_forecast(
    site: str = "AMJK",
    product_group: str = "SW",
    start_date: str = "2010-01-01",
    end_date: str = str(date.today()),  # ← Dynamic!,
    min_months: int = 6,
) -> dict:
    """
    Load shipped product data from stored procedure and compute per-product
    trend direction, momentum, linear regression forecast, and R-squared.

    Returns dict with keys:
        months   - sorted list of YYYY-MM strings
        trends   - dict mapping product_code to list of monthly weights (for chart)
        forecast - list of per-product forecast dicts
        summary  - {total, inc, dec, stb}
    """
    engine = connect_to_database()
    with engine.connect() as conn:
        dbapi_conn = conn.connection
        cursor = dbapi_conn.cursor(dictionary=True)
        cursor.callproc(
            "sp_get_all_shipped_product",
            [site, product_group, start_date, end_date],
        )
        rows = []
        for rs in cursor.stored_results():
            rows.extend(rs.fetchall())
        cursor.close()

    # Aggregate monthly weight per product
    product_monthly = defaultdict(lambda: defaultdict(int))
    all_months = set()

    for row in rows:
        dt = _as_datetime(row.get("Truck_Appointment_Date"))
        if dt is None:
            continue
        ym = dt.strftime("%Y-%m")
        pc = row["Product_Code"]
        wt = int(row["pick_weight"]) if row.get("pick_weight") else 0
        product_monthly[pc][ym] += wt
        all_months.add(ym)

    months_sorted = sorted(all_months)

    # Per-product analysis
    forecast_list = []
    trends_dict = {}

    for pc, monthly in product_monthly.items():
        series = [monthly.get(m, 0) for m in months_sorted]
        active_months = sum(1 for v in series if v > 0)

        if active_months < min_months:
            continue

        overall_avg = sum(series) / len(series) if series else 0
        current_weight = series[-1] if series else 0

        # Momentum: last 6 vs prior 6
        recent_6 = series[-6:] if len(series) >= 6 else series
        prior_6 = series[-12:-6] if len(series) >= 12 else series[: max(len(series) - 6, 1)]
        avg_recent = sum(recent_6) / len(recent_6) if recent_6 else 0
        avg_prior = sum(prior_6) / len(prior_6) if prior_6 else 0
        denom = max(avg_prior, overall_avg * 0.25) if overall_avg > 0 else 1
        momentum = ((avg_recent - avg_prior) / denom) * 100 if denom > 0 else 0
        momentum = max(-300, min(300, momentum))

        # Linear regression
        slope, r2 = _linreg(series)
        forecast_weight = max(0, int(current_weight + slope)) if series else 0

        # YoY
        yoy = None
        if len(series) >= 24:
            last_12 = sum(series[-12:])
            prev_12 = sum(series[-24:-12])
            if prev_12 > 0:
                yoy = round(((last_12 - prev_12) / prev_12) * 100, 1)

        # Direction
        last_6_nonzero = sum(1 for v in series[-6:] if v > 0)
        if last_6_nonzero == 0:
            direction = "DECREASE"
        elif slope > 0 and momentum > 15:
            direction = "INCREASE"
        elif slope < 0 and momentum < -15:
            direction = "DECREASE"
        else:
            direction = "STABLE"

        forecast_list.append(
            {
                "pc": pc,
                "d": direction,
                "ts": round(slope, 2),
                "mp": round(momentum, 1),
                "cw": current_weight,
                "fw": forecast_weight,
                "aw": int(overall_avg),
                "r2": round(r2, 3),
                "yoy": yoy,
                "ma": active_months,
            }
        )
        trends_dict[pc] = series

    inc = sum(1 for f in forecast_list if f["d"] == "INCREASE")
    dec = sum(1 for f in forecast_list if f["d"] == "DECREASE")
    stb = sum(1 for f in forecast_list if f["d"] == "STABLE")

    return {
        "months": months_sorted,
        "trends": trends_dict,
        "forecast": forecast_list,
        "summary": {"total": len(forecast_list), "inc": inc, "dec": dec, "stb": stb},
    }
