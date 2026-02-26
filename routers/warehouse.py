"""
routers/warehouse.py — Warehouse management page route.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Warehouse"])
templates = Jinja2Templates(directory="templates")


@router.get(
    "/warehouse",
    response_class=HTMLResponse,
    summary="Warehouse page",
    description="Warehouse inventory and management dashboard.",
)
async def warehouse(request: Request) -> HTMLResponse:
    """Render the warehouse management page."""
    return templates.TemplateResponse(
        "warehouse/index.html",
        {"request": request, "active_page": "warehouse"},
    )
