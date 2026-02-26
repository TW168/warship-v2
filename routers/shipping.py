"""
routers/shipping.py — Shipping management page route.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Shipping"])
templates = Jinja2Templates(directory="templates")


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
