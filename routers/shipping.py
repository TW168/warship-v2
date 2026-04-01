"""
routers/shipping.py — Shipping management page route.

Includes:
  GET /shipping                             — Shipping management page
  GET /api/shipping/shipped-products        — Call sp_get_all_shipped_product (JSON)
  GET /api/carrier-cost-analysis            — Call sp_carrier_cost_per_pound (JSON)
"""

import datetime
import re
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from database import connect_to_database
from schemas.shipped_product import ShippedProductRow

# Top N Customer Tree Map schema
from schemas.top_customers import TopCustomersResponse, CustomerTreeMapItem

router = APIRouter(tags=["Shipping"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()


_EXCLUDED_TREEMAP_CUSTOMERS = {
    "INTEPLAST GROUP CORP. (AMTOPP)",
    "INTEPLAST GROUP CORP.(AMTOPP ( CFP)",
    "PINNACLE FILMS",
    "AMTOPP WAREHOUSE - HOUSTON",
}


def _normalize_customer_name(name: str) -> str:
    """Normalize customer name for robust exclusion matching."""
    return re.sub(r"\s+", " ", name.upper()).strip()


_EXCLUDED_TREEMAP_CUSTOMERS_NORMALIZED = {
    _normalize_customer_name(name) for name in _EXCLUDED_TREEMAP_CUSTOMERS
}


@router.get(
    "/shipping",
    response_class=HTMLResponse,
    summary="Shipping page",
    description="Shipping orders and logistics management dashboard.",
)
async def shipping(request: Request) -> HTMLResponse:
    """Render the shipping management page."""
    return templates.TemplateResponse(
        "shipping/index.html",
        {"request": request, "active_page": "shipping"},
    )


@router.get(
    "/api/shipping/shipped-products",
    response_model=list[ShippedProductRow],
    summary="All shipped products",
    description=(
        "Calls sp_get_all_shipped_product to return one aggregated row per BL_Number "
        "for the given site, product group, and date range. "
        "Excludes INSERT-* product codes and internal customers. "
        "Only the latest snapshot per BL_Number is included."
    ),
)
async def shipped_products(
    site: str = Query(..., description="Site code, e.g. AMJK"),
    product_group: str = Query(..., description="Product group, e.g. SW"),
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
) -> JSONResponse:
    """Execute sp_get_all_shipped_product via callproc and return results as JSON.

    Uses the raw mysql-connector cursor directly because SQLAlchemy's text("CALL ...")
    does not reliably handle stored-procedure result sets with this driver.
    """
    try:
        start = datetime.date.fromisoformat(start_date.strip("-"))
        end = datetime.date.fromisoformat(end_date.strip("-"))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": f"Invalid date: {exc}"})
    try:
        with _engine.connect() as conn:
            # Get the DBAPI connection from SQLAlchemy connection
            dbapi_conn = conn.connection
            cursor = dbapi_conn.cursor(dictionary=True)
            cursor.callproc(
                "sp_get_all_shipped_product",
                [str(site), str(product_group), start.isoformat(), end.isoformat()],
            )
            rows = []
            for result_set in cursor.stored_results():
                for row in result_set.fetchall():
                    rows.append({
                        "bl_number": row["BL_Number"],
                        "truck_appointment_date": (
                            row["Truck_Appointment_Date"].isoformat()
                            if row["Truck_Appointment_Date"] else None
                        ),
                        "site": row["Site"],
                        "product_group": row["Product_Group"],
                        "product_code": row["Product_Code"],
                        "unit_freight": float(row["Unit_Freight"]) if row["Unit_Freight"] is not None else None,
                        "carrier_id": row["Carrier_ID"],
                        "pallet_count": int(row["pallet_count"]) if row["pallet_count"] is not None else None,
                        "pick_weight": int(row["pick_weight"]) if row["pick_weight"] is not None else None,
                    })
            cursor.close()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(content=rows)


# --- Top N Customer Tree Map Endpoint ---
from fastapi import HTTPException

@router.get(
    "/api/shipping/top-customers",
    response_model=TopCustomersResponse,
    summary="Top N Customers Tree Map",
    description="Returns the top N customers by total shipped weight and freight using sp_bl_lbs_cnt_carrier_customer. Results are suitable for tree map visualization.",
)
async def top_customers_tree_map(
    site: str = Query(..., description="Site code, e.g. AMJK"),
    product_group: str = Query(..., description="Product group, e.g. SW"),
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    top_n: int = Query(20, description="Number of top customers to return"),
) -> TopCustomersResponse:
    """Call sp_bl_lbs_cnt_carrier_customer and return top N customers for tree map visualization."""
    try:
        start = datetime.date.fromisoformat(start_date.strip())
        end = datetime.date.fromisoformat(end_date.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")

    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be <= end_date")

    if top_n < 1:
        raise HTTPException(status_code=422, detail="top_n must be >= 1")

    try:
        with _engine.connect() as conn:
            dbapi_conn = conn.connection
            cursor = dbapi_conn.cursor(dictionary=True)
            rows = []

            # Some DB environments define this SP with different parameter orders.
            # Try the currently observed order first: (site, product_group, start_date, end_date).
            try:
                cursor.callproc(
                    "sp_bl_lbs_cnt_carrier_customer",
                    [str(site), str(product_group), str(start), str(end)],
                )
                for result_set in cursor.stored_results():
                    for row in result_set.fetchall():
                        rows.append(row)
            except Exception as primary_exc:
                # Fallback for legacy order: (start_date, end_date, site, product_group).
                if "Incorrect date value" not in str(primary_exc):
                    raise

                rows = []
                cursor = dbapi_conn.cursor(dictionary=True)
                cursor.callproc(
                    "sp_bl_lbs_cnt_carrier_customer",
                    [str(start), str(end), str(site), str(product_group)],
                )
                for result_set in cursor.stored_results():
                    for row in result_set.fetchall():
                        rows.append(row)

            cursor.close()
            if not rows:
                raise HTTPException(status_code=404, detail="No customer data returned from stored procedure.")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Accept either aggregated SP output or BL-level output and normalize to customer totals.
    if rows and ("Customer_Name" in rows[0] or "Customer" in rows[0]):
        normalized = []
        for row in rows:
            customer_name = str(row.get("Customer_Name") or row.get("Customer") or "Unknown").strip() or "Unknown"
            if _normalize_customer_name(customer_name) in _EXCLUDED_TREEMAP_CUSTOMERS_NORMALIZED:
                continue

            normalized.append(
                {
                    "customer_name": customer_name,
                    "total_weight": float(row.get("pick_weight") or 0.0),
                    "total_freight": float(row.get("freight") or 0.0),
                    "shipment_count": int(row.get("bl_count") or 0),
                }
            )
    elif rows and "Ship_to_Customer" in rows[0]:
        weight_by_customer: dict[str, float] = {}
        freight_by_customer: dict[str, float] = {}
        bls_by_customer: dict[str, set[str]] = {}
        null_bl_count_by_customer: dict[str, int] = {}
        for row in rows:
            customer = str(row.get("Ship_to_Customer") or "Unknown").strip() or "Unknown"
            if _normalize_customer_name(customer) in _EXCLUDED_TREEMAP_CUSTOMERS_NORMALIZED:
                continue

            weight = float(row.get("pick_weight") or 0.0)
            unit_freight_cplb = float(row.get("Unit_Freight") or 0.0)
            bl_number = row.get("BL_Number")

            if customer not in weight_by_customer:
                weight_by_customer[customer] = 0.0
                freight_by_customer[customer] = 0.0
                bls_by_customer[customer] = set()
                null_bl_count_by_customer[customer] = 0

            # Unit_Freight is cents/lb, so convert to dollars.
            weight_by_customer[customer] += weight
            freight_by_customer[customer] += (unit_freight_cplb * weight) / 100.0
            if bl_number:
                bls_by_customer[customer].add(str(bl_number))
            else:
                # BL_Number is NULL — still a real shipment row; count it separately
                # so it is not silently dropped from the shipment total.
                null_bl_count_by_customer[customer] += 1

        normalized = []
        for customer in weight_by_customer:
            normalized.append(
                {
                    "customer_name": customer,
                    "total_weight": weight_by_customer[customer],
                    "total_freight": freight_by_customer[customer],
                    "shipment_count": len(bls_by_customer[customer]) + null_bl_count_by_customer[customer],
                }
            )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected columns in result: {list(rows[0].keys()) if rows else []}",
        )

    # Sort and take top N
    normalized.sort(key=lambda x: x["total_weight"], reverse=True)
    items = [CustomerTreeMapItem(**row) for row in normalized[:top_n]]
    return TopCustomersResponse(items=items)


@router.get(
    "/api/carrier-cost-analysis",
    summary="Carrier cost per pound analysis",
    description=(
        "Calls sp_carrier_cost_per_pound to return one aggregated row per carrier "
        "for the given date range, site, and product group. "
        "All parameters are optional — omitting them returns all data."
    ),
)
async def carrier_cost_analysis(
    date_from: Optional[str] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    site: Optional[str] = Query(None, description="Site code, e.g. AMJK. Omit for all sites."),
    product_group: Optional[str] = Query(None, description="Product group, e.g. SW. Omit for all groups."),
) -> JSONResponse:
    """Execute sp_carrier_cost_per_pound via callproc and return results as JSON.

    Uses the raw mysql-connector cursor directly because SQLAlchemy's text("CALL ...")
    does not reliably handle stored-procedure result sets with this driver.
    """
    # Parse and validate dates
    parsed_from: Optional[datetime.date] = None
    parsed_to: Optional[datetime.date] = None
    if date_from:
        try:
            parsed_from = datetime.date.fromisoformat(date_from.strip())
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": f"Invalid date_from: {exc}"})
    if date_to:
        try:
            parsed_to = datetime.date.fromisoformat(date_to.strip())
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": f"Invalid date_to: {exc}"})
    if parsed_from and parsed_to and parsed_from > parsed_to:
        return JSONResponse(status_code=400, content={"error": "date_from must be <= date_to"})

    # Normalize empty strings to None so the SP receives NULL
    site_param = site.strip() if site and site.strip() else None
    pg_param = product_group.strip() if product_group and product_group.strip() else None

    try:
        with _engine.connect() as conn:
            dbapi_conn = conn.connection
            cursor = dbapi_conn.cursor(dictionary=True)
            cursor.callproc(
                "sp_carrier_cost_per_pound",
                [
                    parsed_from.isoformat() if parsed_from else None,
                    parsed_to.isoformat() if parsed_to else None,
                    site_param,
                    pg_param,
                ],
            )
            rows = []
            for result_set in cursor.stored_results():
                for row in result_set.fetchall():
                    rows.append({
                        "carrier_id": row["Carrier_ID"],
                        "bl_count": int(row["bl_count"]) if row["bl_count"] is not None else 0,
                        "total_weight": int(row["total_weight"]) if row["total_weight"] is not None else 0,
                        "total_pallets": int(row["total_pallets"]) if row["total_pallets"] is not None else 0,
                        "total_freight_cost": float(row["total_freight_cost"]) if row["total_freight_cost"] is not None else 0.0,
                        "cost_per_pound": float(row["cost_per_pound"]) if row["cost_per_pound"] is not None else 0.0,
                    })
            cursor.close()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(content=rows)
