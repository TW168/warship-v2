"""
routers/shipping.py — Shipping management page route.

Includes:
  GET /shipping                             — Shipping management page
  GET /api/shipping/shipped-products        — Call sp_get_all_shipped_product (JSON)
"""

import datetime

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
