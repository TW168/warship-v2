"""
routers/shipping.py — Shipping management page route.

Includes:
  GET /shipping                             — Shipping management page
  GET /api/shipping/shipped-products        — Call sp_get_all_shipped_product (JSON)
  GET /api/carrier-cost-analysis            — Call sp_carrier_cost_per_pound (JSON)
"""

import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from database import connect_to_database
from schemas.shipped_product import ShippedProductRow

router = APIRouter(tags=["Shipping"])
templates = Jinja2Templates(directory="templates")

_engine = connect_to_database()


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
            # Unwrap to the underlying mysql-connector-python connection
            raw = conn.connection.driver_connection
            cursor = raw.cursor(dictionary=True)
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
            raw = conn.connection.driver_connection
            cursor = raw.cursor(dictionary=True)
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
