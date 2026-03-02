"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
  GET /maintenance/input — data entry form
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
