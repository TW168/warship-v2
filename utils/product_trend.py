"""Legacy compatibility helpers for product trend analytics.

These helpers now read from Warship DB stored procedure data only.
"""

import pandas as pd

from utils.product_trend_service import load_product_data_from_sp


def build_product_trend_model(csv_path: str | None = None) -> pd.DataFrame:
    """Build a product trend model from stored-procedure shipment rows.

    The ``csv_path`` argument is retained for backward compatibility but ignored.
    """
    rows = load_product_data_from_sp()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["year_month", "product_code", "total_weight_lbs", "shipment_count"])

    df["Truck_Appointment_Date"] = pd.to_datetime(df["Truck_Appointment_Date"], errors="coerce")
    df = df.dropna(subset=["Truck_Appointment_Date", "Product_Code"])
    df["year_month"] = df["Truck_Appointment_Date"].dt.strftime("%Y-%m")
    df["pick_weight"] = pd.to_numeric(df["pick_weight"], errors="coerce").fillna(0)

    trend = (
        df.groupby(["year_month", "Product_Code"], as_index=False)
        .agg(total_weight_lbs=("pick_weight", "sum"), shipment_count=("BL_Number", "count"))
        .rename(columns={"Product_Code": "product_code"})
        .sort_values(["year_month", "total_weight_lbs"], ascending=[True, False])
    )
    return trend


def get_top_products_by_month(csv_path: str | None = None, top_n: int = 5) -> dict:
    """Get top N products by monthly shipped weight from DB data."""
    trend = build_product_trend_model(csv_path)
    result: dict[str, list[dict]] = {}
    for month in trend["year_month"].unique():
        month_data = trend[trend["year_month"] == month].head(top_n)
        result[month] = month_data[["product_code", "total_weight_lbs", "shipment_count"]].to_dict("records")
    return result


def get_product_trend_over_time(csv_path: str | None, product_code: str) -> pd.DataFrame:
    """Get month-by-month shipped-weight trend for one product code."""
    trend = build_product_trend_model(csv_path)
    return trend[trend["product_code"] == product_code].sort_values("year_month")