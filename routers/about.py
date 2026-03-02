"""
routers/about.py — About section routes.

Handles:
  GET /about             — About page (tech stack, version info)
  GET /about/architectural — Software Architecture document (Markdown → HTML + scrollspy TOC)
  GET /about/who-are-we  — Who Are We page (team picture placeholder)
"""

from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pygments.formatters import HtmlFormatter

router = APIRouter(tags=["About"])
templates = Jinja2Templates(directory="templates")

# Path to the Software Architectural document
ARCHITECTURAL_MD = Path("docs/architectural.md")


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


@router.get(
    "/about/architectural",
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
        "about/architectural.html",
        {
            "request": request,
            "active_page": "about_arch",
            "html_content": html_content,
            "pygments_css": pygments_css,
        },
    )


@router.get(
    "/about/who-are-we",
    response_class=HTMLResponse,
    summary="Who Are We page",
    description="Team introduction page with a group photo and team information.",
)
async def who_are_we(request: Request) -> HTMLResponse:
    """Render the Who Are We team page."""
    return templates.TemplateResponse(
        "about/who_are_we.html",
        {"request": request, "active_page": "about_who"},
    )
