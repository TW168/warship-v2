"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
  GET /maintenance/input        — data entry form
  GET /maintenance/architectural — rendered Markdown + Pygments + scrollspy TOC
"""

from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pygments.formatters import HtmlFormatter

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# Path to the Software Architectural document
ARCHITECTURAL_MD = Path("docs/architectural.md")


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
    "/architectural",
    response_class=HTMLResponse,
    summary="Software Architectural page",
    description=(
        "Renders the Software Architecture document from Markdown to HTML "
        "with Pygments syntax highlighting and a JS-generated Bootstrap scrollspy TOC sidebar."
    ),
)
async def architectural(request: Request) -> HTMLResponse:
    """
    Read the architectural Markdown file, convert to HTML with Pygments
    syntax highlighting, and pass to the template for scrollspy rendering.
    """
    # Read the Markdown source document
    md_text = ARCHITECTURAL_MD.read_text(encoding="utf-8")

    # Convert Markdown to HTML using codehilite (Pygments) and fenced code blocks
    md_processor = markdown.Markdown(
        extensions=["codehilite", "fenced_code", "tables", "toc", "attr_list"],
        extension_configs={
            "codehilite": {"css_class": "codehilite", "linenums": False},
            "toc": {"permalink": False},
        },
    )
    html_content = md_processor.convert(md_text)

    # Generate the Pygments CSS for the default light theme
    formatter = HtmlFormatter(style="default")
    pygments_css = formatter.get_style_defs(".codehilite")

    return templates.TemplateResponse(
        "maintenance/architectural.html",
        {
            "request": request,
            "active_page": "maintenance",
            "html_content": html_content,
            "pygments_css": pygments_css,
        },
    )
