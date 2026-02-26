"""
routers/about.py — About page route.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["About"])
templates = Jinja2Templates(directory="templates")


@router.get(
    "/about",
    response_class=HTMLResponse,
    summary="About page",
    description="Information about the Warship application, its purpose, and the development team.",
)
async def about(request: Request) -> HTMLResponse:
    """Render the about page."""
    return templates.TemplateResponse(
        "about/index.html",
        {"request": request, "active_page": "about"},
    )
