"""
main.py — Warship application entry point.

Creates the FastAPI app, registers all routers, and mounts static files.
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Load .env from the same directory as main.py — works regardless of cwd
load_dotenv(Path(__file__).parent / ".env")

# Initialize logging before importing routers
from logging_config import setup_logging, get_logger
setup_logging(level="INFO")
logger = get_logger(__name__)

from routers import health, home, warehouse, shipping, tsr_prep, maintenance, about
from routers.maintenance.silos.api import public_router as silos_public_router

# Create the FastAPI application with metadata for Swagger UI
app = FastAPI(
    title="Warship",
    description="Warehouse and Shipping Management System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

templates = Jinja2Templates(directory="templates")

# Mount the static files directory so templates can reference /static/...
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register all routers
logger.info("Registering application routers...")
app.include_router(health.router)
app.include_router(home.router)
app.include_router(warehouse.router)
app.include_router(shipping.router)
app.include_router(tsr_prep.router)
app.include_router(maintenance.router)
app.include_router(about.router)
app.include_router(silos_public_router)
logger.info("All routers registered successfully")


@app.get("/silos-status", response_class=HTMLResponse, include_in_schema=False)
async def silos_status(request: Request) -> HTMLResponse:
    """Render the Silos Status dashboard at a root-level URL (no redirect)."""
    return templates.TemplateResponse(
        "maintenance/site_status_upload.html",
        {"request": request, "active_page": "silos_status"},
    )
