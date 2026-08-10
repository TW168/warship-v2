"""routers/shipping — Shipping management pages and APIs."""

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
    "/shipping/saia-ltl-upload",
    response_class=HTMLResponse,
    summary="SAIA LTL freight upload",
    description="Upload and manage SAIA LTL freight load and count exception reports.",
)
async def saia_ltl_upload(request: Request) -> HTMLResponse:
    """Render the SAIA LTL freight upload page."""
    return templates.TemplateResponse(
        "shipping/saia_ltl_upload.html",
        {"request": request, "active_page": "shipping"},
    )


@router.get(
    "/api/shipping/shipped-products",
    response_model=list[ShippedProductRow],
    summary="All shipped products",
    description=(
        "Returns all records from sp_get_all_shipped_product (shipped product "
        "detail). Optional date range, site, product group filters."
    ),
)
async def shipped_products(
    site: Optional[str] = Query(None),
    product_group: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> list[ShippedProductRow]:
    """Return all shipped product records from the stored procedure."""
    with _engine.connect() as conn:
        cursor = conn.connection.cursor(dictionary=True)
        try:
            cursor.callproc(
                "sp_get_all_shipped_product",
                [
                    date_from,
                    date_to,
                    site,
                    product_group,
                ],
            )
            rows = []
            for result_set in cursor.stored_results():
                for row in result_set.fetchall():
                    rows.append(ShippedProductRow(
                        bl_number=row["BL_Number"],
                        truck_appointment_date=(
                            row["Truck_Appointment_Date"].isoformat()
                            if row["Truck_Appointment_Date"] else None
                        ),
                        site=row["Site"],
                        product_group=row["Product_Group"],
                        product_code=row["Product_Code"],
                        unit_freight=float(row["Unit_Freight"]) if row["Unit_Freight"] is not None else None,
                        carrier_id=row["Carrier_ID"],
                        pallet_count=int(row["pallet_count"]) if row["pallet_count"] is not None else None,
                        pick_weight=int(row["pick_weight"]) if row["pick_weight"] is not None else None,
                    ))
            cursor.close()
        except Exception as exc:
            return []

    return rows


@router.get(
    "/api/carrier-cost-analysis",
    summary="Carrier cost per pound",
    description=(
        "Returns carrier cost analysis from sp_carrier_cost_per_pound. "
        "Optional date range, site, product group filters."
    ),
)
async def carrier_cost_analysis(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    site: Optional[str] = Query(None),
    product_group: Optional[str] = Query(None),
) -> JSONResponse:
    """Return carrier cost analysis from the stored procedure."""
    try:
        with _engine.connect() as conn:
            cursor = conn.connection.cursor(dictionary=True)
            # Workaround: in this version of MySQL, date formats are handled differently.
            # Parse the date strings if provided
            parsed_from = None
            parsed_to = None
            if date_from:
                try:
                    parsed_from = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if date_to:
                try:
                    parsed_to = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()
                except ValueError:
                    pass

            site_param = site if site else None
            pg_param = product_group if product_group else None

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


# Include SAIA LTL sub-router
from routers.shipping.saia_ltl import router as saia_ltl_router
router.include_router(saia_ltl_router)
