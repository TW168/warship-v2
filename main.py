"""
main.py — Warship application entry point.

Creates the FastAPI app, registers all routers, and mounts static files.
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Load .env from the same directory as main.py — works regardless of cwd
load_dotenv(Path(__file__).parent / ".env")

from routers import health, home, warehouse, shipping, tsr_prep, maintenance, about

# Create the FastAPI application with metadata for Swagger UI
app = FastAPI(
    title="Warship",
    description="Warehouse and Shipping Management System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount the static files directory so templates can reference /static/...
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register all routers
app.include_router(health.router)
app.include_router(home.router)
app.include_router(warehouse.router)
app.include_router(shipping.router)
app.include_router(tsr_prep.router)
app.include_router(maintenance.router)
app.include_router(about.router)
