"""
routers/maintenance/truck_load_map.py — Truck Load Map planning tool.

Provides an interactive drag-and-drop pallet placement tool for planning
truck trailer loads.  The product catalogue (pallet dimensions and gross
weights) is loaded from the ``warship.Product_desc_size`` table at page load
time and injected into the template.

If the database is unreachable the page still loads with an empty product
dropdown — the core 3-D canvas and manual entry forms remain fully functional.

Routes:
    GET /truck-load-map — Interactive truck trailer load planning page
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# One shared engine for this module (created at import time)
_engine = connect_to_database()
logger = get_router_logger("maintenance.truck_load_map")


@router.get(
    "/truck-load-map",
    response_class=HTMLResponse,
    summary="Truck Load Map",
    description=(
        "Interactive truck trailer load planning tool. "
        "Drag-and-drop pallet placement with real product dimensions and "
        "weights loaded from ``warship.Product_desc_size``. "
        "Degrades gracefully when the database is unreachable — the canvas "
        "and manual-entry sidebar remain functional with an empty catalogue."
    ),
)
async def truck_load_map(request: Request) -> HTMLResponse:
    """Render the Truck Load Map interactive planning page.

    Queries ``warship.Product_desc_size`` to populate the product dropdown
    in the Add Pallet sidebar card.  On any DB error the page renders with
    an empty product list rather than returning an error response.
    """
    products: list[dict] = []
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        id,
                        product_description,
                        product,
                        pallet_length,
                        pallet_width,
                        pallet_height,
                        product_groww_weight
                    FROM warship.Product_desc_size
                    ORDER BY product_description
                    """
                )
            ).fetchall()
            products = [
                {
                    "id":                   r.id,
                    "product_description":  r.product_description,
                    "product":              r.product,
                    "pallet_length":        float(r.pallet_length),
                    "pallet_width":         float(r.pallet_width),
                    "pallet_height":        float(r.pallet_height),
                    "product_groww_weight": float(r.product_groww_weight),
                }
                for r in rows
            ]
    except Exception as e:
        # Graceful degradation — DB unavailable at page load is non-fatal
        logger.warning(f"Failed to load product dimensions from database: {e}")
        products = []

    return templates.TemplateResponse(
        "maintenance/truck_load_map.html",
        {"request": request, "active_page": "truck_load_map", "products": products},
    )
