"""Sales summary analysis script using pandas.

This script reads the ``sales_summary`` table from the Warship database,
creates a cleaned line-item dataframe, and produces analysis sections A-F.
Results are written to ``sales_analysis_output.txt`` in the repository root.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

import pandas as pd
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database import connect_to_database

OUTPUT_FILE = REPO_ROOT / "sales_analysis_output.txt"


def format_int(value: float | int) -> str:
    """Format a numeric value as an integer with thousands separators."""
    return f"{float(value):,.0f}"


def format_currency(value: float | int) -> str:
    """Format a numeric value as USD with thousands separators and 2 decimals."""
    return f"${float(value):,.2f}"


def format_pct(value: float | int) -> str:
    """Format a ratio as percent with 2 decimals."""
    return f"{float(value) * 100:,.2f}%"


def section_header(title: str) -> list[str]:
    """Return a standardized section header block."""
    return ["", "=" * 90, title, "=" * 90]


def to_lines(df: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    """Render a dataframe as plain text lines for output."""
    if df.empty:
        return ["(no data)"]
    return [df.loc[:, list(columns)].to_string(index=False)]


def load_sales_summary_dataframe() -> pd.DataFrame:
    """Load raw sales_summary rows from MySQL into a pandas dataframe."""
    engine = connect_to_database()
    query = text(
        """
        SELECT
            id,
            source_file,
            uploaded_at_utc,
            run_date,
            business_date,
            product_class,
            product_name,
            daily_order_qty,
            daily_order_unit_price,
            mtd_order_qty,
            mtd_order_unit_price,
            daily_shipment_qty,
            daily_shipment_unit_price,
            mtd_shipment_qty,
            mtd_shipment_unit_price,
            mtd_shipment_unit_frt,
            monthend_backlog_qty,
            total_backlog_qty,
            total_backlog_unit_price,
            target_qty_klb,
            is_total_row
        FROM sales_summary
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return df

    df["run_date"] = pd.to_datetime(df["run_date"], errors="coerce")
    df["business_date"] = pd.to_datetime(df["business_date"], errors="coerce")
    df["uploaded_at_utc"] = pd.to_datetime(df["uploaded_at_utc"], errors="coerce")

    numeric_cols = [
        "daily_order_qty",
        "daily_order_unit_price",
        "mtd_order_qty",
        "mtd_order_unit_price",
        "daily_shipment_qty",
        "daily_shipment_unit_price",
        "mtd_shipment_qty",
        "mtd_shipment_unit_price",
        "mtd_shipment_unit_frt",
        "monthend_backlog_qty",
        "total_backlog_qty",
        "total_backlog_unit_price",
        "target_qty_klb",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["is_total_row"] = pd.to_numeric(df["is_total_row"], errors="coerce").fillna(0).astype(int)
    df["product_name"] = df["product_name"].fillna("")
    df["product_class"] = df["product_class"].fillna("")

    return df


def build_df_items(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Create cleaned line-item dataframe by excluding subtotal/rollup rows."""
    if df_raw.empty:
        return df_raw.copy()

    product_name_upper = df_raw["product_name"].str.upper()
    product_class_clean = df_raw["product_class"].str.strip()

    subtotal_mask = (
        (df_raw["is_total_row"] == 1)
        | product_name_upper.str.contains(r"TTL:|WRTTL", regex=True, na=False)
        | product_class_clean.eq("")
    )

    df_items = df_raw.loc[~subtotal_mask].copy()

    # Row-level revenue columns used in all sections where revenue is aggregated.
    df_items["daily_order_revenue"] = df_items["daily_order_qty"] * df_items["daily_order_unit_price"]
    df_items["daily_shipment_revenue"] = df_items["daily_shipment_qty"] * df_items["daily_shipment_unit_price"]
    df_items["mtd_order_revenue"] = df_items["mtd_order_qty"] * df_items["mtd_order_unit_price"]
    df_items["mtd_shipment_revenue"] = df_items["mtd_shipment_qty"] * df_items["mtd_shipment_unit_price"]
    df_items["backlog_value"] = df_items["total_backlog_qty"] * df_items["total_backlog_unit_price"]

    return df_items


def latest_business_snapshot(df_items: pd.DataFrame) -> tuple[pd.Timestamp, pd.DataFrame]:
    """Return latest business_date and rows for that single business_date."""
    latest_date = df_items["business_date"].max()
    return latest_date, df_items.loc[df_items["business_date"] == latest_date].copy()


def analysis_a_sales_performance(df_latest: pd.DataFrame) -> list[str]:
    """Section A: Daily/MTD qty and revenue performance for latest business_date."""
    totals = {
        "Daily Order Qty": df_latest["daily_order_qty"].sum(),
        "Daily Shipment Qty": df_latest["daily_shipment_qty"].sum(),
        "MTD Order Qty": df_latest["mtd_order_qty"].sum(),
        "MTD Shipment Qty": df_latest["mtd_shipment_qty"].sum(),
        "Daily Order Revenue": df_latest["daily_order_revenue"].sum(),
        "Daily Shipment Revenue": df_latest["daily_shipment_revenue"].sum(),
        "MTD Order Revenue": df_latest["mtd_order_revenue"].sum(),
        "MTD Shipment Revenue": df_latest["mtd_shipment_revenue"].sum(),
    }

    lines = section_header("A) SALES PERFORMANCE (LATEST BUSINESS_DATE)")
    lines.append("Daily vs MTD Volumes")
    lines.append(f"- Daily Order Qty:      {format_int(totals['Daily Order Qty'])}")
    lines.append(f"- Daily Shipment Qty:   {format_int(totals['Daily Shipment Qty'])}")
    lines.append(f"- MTD Order Qty:        {format_int(totals['MTD Order Qty'])}")
    lines.append(f"- MTD Shipment Qty:     {format_int(totals['MTD Shipment Qty'])}")
    lines.append("")
    lines.append("Daily vs MTD Revenue")
    lines.append(f"- Daily Order Revenue:    {format_currency(totals['Daily Order Revenue'])}")
    lines.append(f"- Daily Shipment Revenue: {format_currency(totals['Daily Shipment Revenue'])}")
    lines.append(f"- MTD Order Revenue:      {format_currency(totals['MTD Order Revenue'])}")
    lines.append(f"- MTD Shipment Revenue:   {format_currency(totals['MTD Shipment Revenue'])}")
    return lines


def analysis_b_pricing(df_latest: pd.DataFrame) -> list[str]:
    """Section B: Weighted pricing, spread, and freight percentage by class."""
    grouped = (
        df_latest.groupby("product_class", as_index=False)
        .agg(
            mtd_order_qty_sum=("mtd_order_qty", "sum"),
            mtd_ship_qty_sum=("mtd_shipment_qty", "sum"),
            mtd_order_rev_sum=("mtd_order_revenue", "sum"),
            mtd_ship_rev_sum=("mtd_shipment_revenue", "sum"),
            mtd_freight_value_sum=("mtd_shipment_unit_frt", lambda s: (s * df_latest.loc[s.index, "mtd_shipment_qty"]).sum()),
        )
    )

    grouped["wavg_mtd_order_unit_price"] = grouped["mtd_order_rev_sum"] / grouped["mtd_order_qty_sum"].replace(0, pd.NA)
    grouped["wavg_mtd_shipment_unit_price"] = grouped["mtd_ship_rev_sum"] / grouped["mtd_ship_qty_sum"].replace(0, pd.NA)
    grouped["price_spread_ship_minus_order"] = (
        grouped["wavg_mtd_shipment_unit_price"] - grouped["wavg_mtd_order_unit_price"]
    )
    grouped["freight_pct_of_ship_price"] = grouped["mtd_freight_value_sum"] / grouped["mtd_ship_rev_sum"].replace(0, pd.NA)

    show = grouped[
        [
            "product_class",
            "wavg_mtd_order_unit_price",
            "wavg_mtd_shipment_unit_price",
            "price_spread_ship_minus_order",
            "freight_pct_of_ship_price",
        ]
    ].fillna(0.0)

    show["wavg_mtd_order_unit_price"] = show["wavg_mtd_order_unit_price"].map(format_currency)
    show["wavg_mtd_shipment_unit_price"] = show["wavg_mtd_shipment_unit_price"].map(format_currency)
    show["price_spread_ship_minus_order"] = show["price_spread_ship_minus_order"].map(format_currency)
    show["freight_pct_of_ship_price"] = show["freight_pct_of_ship_price"].map(format_pct)

    lines = section_header("B) PRICING ANALYSIS (LATEST BUSINESS_DATE)")
    lines.extend(to_lines(show, show.columns))
    return lines


def analysis_c_backlog(df_latest: pd.DataFrame) -> list[str]:
    """Section C: Backlog totals and top backlog products."""
    backlog_by_class = (
        df_latest.groupby("product_class", as_index=False)
        .agg(
            total_backlog_qty=("total_backlog_qty", "sum"),
            total_backlog_value=("backlog_value", "sum"),
        )
        .sort_values("total_backlog_qty", ascending=False)
    )
    backlog_by_class["total_backlog_qty"] = backlog_by_class["total_backlog_qty"].map(format_int)
    backlog_by_class["total_backlog_value"] = backlog_by_class["total_backlog_value"].map(format_currency)

    top_products = (
        df_latest.assign(product=lambda d: (d["product_class"].str.strip() + " " + d["product_name"].str.strip()).str.strip())
        .groupby("product", as_index=False)
        .agg(total_backlog_qty=("total_backlog_qty", "sum"), backlog_value=("backlog_value", "sum"))
        .sort_values("total_backlog_qty", ascending=False)
        .head(10)
    )
    top_products["total_backlog_qty"] = top_products["total_backlog_qty"].map(format_int)
    top_products["backlog_value"] = top_products["backlog_value"].map(format_currency)

    monthend_total = df_latest["monthend_backlog_qty"].sum()
    total_backlog = df_latest["total_backlog_qty"].sum()

    lines = section_header("C) BACKLOG & DEMAND (LATEST BUSINESS_DATE)")
    lines.append("Backlog by Product Class")
    lines.extend(to_lines(backlog_by_class, backlog_by_class.columns))
    lines.append("")
    lines.append("Top 10 Products by Total Backlog Qty")
    lines.extend(to_lines(top_products, top_products.columns))
    lines.append("")
    lines.append("Backlog Rolling Forward")
    lines.append(f"- Monthend Backlog Qty (sum): {format_int(monthend_total)}")
    lines.append(f"- Total Backlog Qty (sum):    {format_int(total_backlog)}")
    lines.append(f"- Difference (Total - Monthend): {format_int(total_backlog - monthend_total)}")
    return lines


def analysis_d_target_achievement(df_latest: pd.DataFrame) -> list[str]:
    """Section D: Target achievement by product and class.

    Assumption flagged: target_qty_klb is in klb while shipment qty is in lb,
    so shipment is converted to klb by dividing by 1000.
    """
    df_target = df_latest.copy()
    df_target["mtd_shipment_klb"] = df_target["mtd_shipment_qty"] / 1000.0
    df_target["target_achievement_ratio"] = df_target["mtd_shipment_klb"] / df_target["target_qty_klb"].replace(0, pd.NA)

    class_perf = (
        df_target.groupby("product_class", as_index=False)
        .agg(
            mtd_shipment_klb=("mtd_shipment_klb", "sum"),
            target_qty_klb=("target_qty_klb", "sum"),
        )
    )
    class_perf["target_achievement_ratio"] = class_perf["mtd_shipment_klb"] / class_perf["target_qty_klb"].replace(0, pd.NA)

    class_show = class_perf.copy().fillna(0.0)
    class_show["mtd_shipment_klb"] = class_show["mtd_shipment_klb"].map(lambda v: f"{float(v):,.2f}")
    class_show["target_qty_klb"] = class_show["target_qty_klb"].map(lambda v: f"{float(v):,.2f}")
    class_show["target_achievement_ratio"] = class_show["target_achievement_ratio"].map(format_pct)

    under = class_perf.loc[class_perf["target_achievement_ratio"] < 0.80, ["product_class", "target_achievement_ratio"]].copy()
    over = class_perf.loc[class_perf["target_achievement_ratio"] > 1.10, ["product_class", "target_achievement_ratio"]].copy()

    if not under.empty:
        under["target_achievement_ratio"] = under["target_achievement_ratio"].map(format_pct)
    if not over.empty:
        over["target_achievement_ratio"] = over["target_achievement_ratio"].map(format_pct)

    lines = section_header("D) TARGET ACHIEVEMENT (LATEST BUSINESS_DATE)")
    lines.append("Assumption: target_qty_klb is klb; mtd_shipment_qty converted from lb to klb by dividing by 1000.")
    lines.append("")
    lines.append("Target Achievement by Product Class")
    lines.extend(to_lines(class_show, class_show.columns))
    lines.append("")
    lines.append("Under-performers (< 80%)")
    lines.extend(to_lines(under, under.columns))
    lines.append("")
    lines.append("Over-performers (> 110%)")
    lines.extend(to_lines(over, over.columns))
    return lines


def analysis_e_product_mix(df_latest: pd.DataFrame) -> list[str]:
    """Section E: Product mix by class and top products."""
    total_qty = df_latest["mtd_shipment_qty"].sum()
    total_rev = df_latest["mtd_shipment_revenue"].sum()

    mix_class = (
        df_latest.groupby("product_class", as_index=False)
        .agg(mtd_shipment_qty=("mtd_shipment_qty", "sum"), mtd_shipment_revenue=("mtd_shipment_revenue", "sum"))
    )
    mix_class["qty_share"] = mix_class["mtd_shipment_qty"] / (total_qty if total_qty else pd.NA)
    mix_class["revenue_share"] = mix_class["mtd_shipment_revenue"] / (total_rev if total_rev else pd.NA)

    mix_show = mix_class.copy().fillna(0.0)
    mix_show["mtd_shipment_qty"] = mix_show["mtd_shipment_qty"].map(format_int)
    mix_show["mtd_shipment_revenue"] = mix_show["mtd_shipment_revenue"].map(format_currency)
    mix_show["qty_share"] = mix_show["qty_share"].map(format_pct)
    mix_show["revenue_share"] = mix_show["revenue_share"].map(format_pct)

    by_product = df_latest.assign(product=lambda d: (d["product_class"].str.strip() + " " + d["product_name"].str.strip()).str.strip())
    top_qty = (
        by_product.groupby("product", as_index=False)
        .agg(mtd_shipment_qty=("mtd_shipment_qty", "sum"))
        .sort_values("mtd_shipment_qty", ascending=False)
        .head(10)
    )
    top_rev = (
        by_product.groupby("product", as_index=False)
        .agg(mtd_shipment_revenue=("mtd_shipment_revenue", "sum"))
        .sort_values("mtd_shipment_revenue", ascending=False)
        .head(10)
    )

    top_qty["mtd_shipment_qty"] = top_qty["mtd_shipment_qty"].map(format_int)
    top_rev["mtd_shipment_revenue"] = top_rev["mtd_shipment_revenue"].map(format_currency)

    lines = section_header("E) PRODUCT MIX (LATEST BUSINESS_DATE)")
    lines.append("Product Class Mix")
    lines.extend(to_lines(mix_show, mix_show.columns))
    lines.append("")
    lines.append("Top 10 Products by MTD Shipment Qty")
    lines.extend(to_lines(top_qty, top_qty.columns))
    lines.append("")
    lines.append("Top 10 Products by MTD Shipment Revenue")
    lines.extend(to_lines(top_rev, top_rev.columns))
    return lines


def analysis_f_time_series(df_items: pd.DataFrame) -> list[str]:
    """Section F: Time series using latest snapshot per business_date only."""
    latest_upload_per_date = (
        df_items.groupby("business_date", as_index=False)["uploaded_at_utc"].max().rename(columns={"uploaded_at_utc": "latest_uploaded_at_utc"})
    )

    df_ts = df_items.merge(
        latest_upload_per_date,
        on="business_date",
        how="inner",
    )
    df_ts = df_ts.loc[df_ts["uploaded_at_utc"] == df_ts["latest_uploaded_at_utc"]].copy()

    shipment_trend = (
        df_ts.groupby("business_date", as_index=False)
        .agg(daily_shipment_qty=("daily_shipment_qty", "sum"))
        .sort_values("business_date")
    )
    backlog_trend = (
        df_ts.groupby("business_date", as_index=False)
        .agg(total_backlog_qty=("total_backlog_qty", "sum"))
        .sort_values("business_date")
    )

    shipment_show = shipment_trend.copy()
    backlog_show = backlog_trend.copy()
    shipment_show["business_date"] = shipment_show["business_date"].dt.strftime("%Y-%m-%d")
    backlog_show["business_date"] = backlog_show["business_date"].dt.strftime("%Y-%m-%d")
    shipment_show["daily_shipment_qty"] = shipment_show["daily_shipment_qty"].map(format_int)
    backlog_show["total_backlog_qty"] = backlog_show["total_backlog_qty"].map(format_int)

    lines = section_header("F) TIME SERIES (ALL BUSINESS_DATES)")
    lines.append("Daily Shipment Qty Trend")
    lines.extend(to_lines(shipment_show, shipment_show.columns))
    lines.append("")
    lines.append("Total Backlog Trend")
    lines.extend(to_lines(backlog_show, backlog_show.columns))
    return lines


def main() -> None:
    """Execute all analysis sections and write report to sales_analysis_output.txt."""
    df_raw = load_sales_summary_dataframe()
    if df_raw.empty:
        OUTPUT_FILE.write_text("No rows found in sales_summary table.\n", encoding="utf-8")
        print(f"No data found. Wrote {OUTPUT_FILE}")
        return

    df_items = build_df_items(df_raw)
    if df_items.empty:
        OUTPUT_FILE.write_text(
            "All rows were filtered out as subtotal/rollup rows. No line-item data available.\n",
            encoding="utf-8",
        )
        print(f"No line-item data after filtering. Wrote {OUTPUT_FILE}")
        return

    latest_date, df_latest = latest_business_snapshot(df_items)

    output_lines: list[str] = []
    output_lines.append("SALES SUMMARY ANALYSIS (PANDAS)")
    output_lines.append("Data source: warship.sales_summary")
    output_lines.append(f"Raw rows: {len(df_raw):,}")
    output_lines.append(f"Line-item rows after filtering: {len(df_items):,}")
    output_lines.append(f"Latest business_date used for point-in-time sections: {latest_date.strftime('%Y-%m-%d')}")

    output_lines.extend(analysis_a_sales_performance(df_latest))
    output_lines.extend(analysis_b_pricing(df_latest))
    output_lines.extend(analysis_c_backlog(df_latest))
    output_lines.extend(analysis_d_target_achievement(df_latest))
    output_lines.extend(analysis_e_product_mix(df_latest))
    output_lines.extend(analysis_f_time_series(df_items))

    OUTPUT_FILE.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    print(f"Analysis written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
