"""
routers/tsr_prep.py — TSR Prep page route.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["TSR Prep"])
templates = Jinja2Templates(directory="templates")


@router.get(
    "/tsr-prep",
    response_class=HTMLResponse,
    summary="TSR Prep page",
    description="Technical Support Request preparation and tracking dashboard.",
)
async def tsr_prep(request: Request) -> HTMLResponse:
    """Render the TSR Prep page."""
    return templates.TemplateResponse(
        "tsr_prep/index.html",
        {"request": request, "active_page": "tsr_prep"},
    )
