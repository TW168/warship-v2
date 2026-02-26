"""
routers/home.py — Home and Press page routes.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Home"])
templates = Jinja2Templates(directory="templates")


@router.get(
    "/",
    response_class=HTMLResponse,
    summary="Home page",
    description="Main landing page displaying weather forecast images side by side.",
)
async def home(request: Request) -> HTMLResponse:
    """Render the home page."""
    return templates.TemplateResponse(
        "home/index.html",
        {"request": request, "active_page": "home"},
    )


@router.get(
    "/press",
    response_class=HTMLResponse,
    summary="Press page",
    description="Press releases and news sub-page under Home.",
)
async def press(request: Request) -> HTMLResponse:
    """Render the press sub-page."""
    return templates.TemplateResponse(
        "home/press.html",
        {"request": request, "active_page": "press"},
    )
