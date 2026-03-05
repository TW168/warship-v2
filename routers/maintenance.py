"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
  GET /maintenance/input            — data entry form
  GET /maintenance/frt-validation   — Freight ¢/lb by Product Code validation tool
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")


@router.get(
    "/input",
    response_class=HTMLResponse,
    summary="Maintenance Input page",
    description="Data entry form for warehouse and shipping maintenance records.",
)
async def maintenance_input(request: Request) -> HTMLResponse:
    """Render the maintenance data entry form."""
    return templates.TemplateResponse(
        "maintenance/input.html",
        {"request": request, "active_page": "maintenance"},
    )


@router.get(
    "/frt-validation",
    response_class=HTMLResponse,
    summary="Freight ¢/lb by Product Code Validation",
    description=(
        "Interactive tool to validate the Freight ¢/lb by Product Code chart. "
        "Steps: raw API data table, per-product median check, top-50 weight filter, BL number lookup."
    ),
)
async def frt_validation(request: Request) -> HTMLResponse:
    """Render the freight ¢/lb validation tool page."""
    return templates.TemplateResponse(
        "maintenance/frt_validation.html",
        {"request": request, "active_page": "frt_validation"},
    )
