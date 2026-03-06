"""
routers/warehouse.py — Warehouse management page routes.

Handles:
  GET /warehouse                          — Warehouse dashboard page
  GET /api/warehouse/udc-hourly           — Proxy: today's UDC hourly missions
  GET /api/warehouse/udc-summary          — Proxy: UDC summary by date range
  GET /api/warehouse/ash-summary          — Proxy: ASH event summary by date range
  GET /api/warehouse/ash-descriptions     — Proxy: full ASH description catalog
"""

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Warehouse"])
templates = Jinja2Templates(directory="templates")

_WH_API = "http://172.17.15.228:8000"
_TIMEOUT = 15.0


@router.get(
    "/warehouse",
    response_class=HTMLResponse,
    summary="Warehouse page",
    description="Warehouse operations dashboard: UDC hourly activity, UDC history trend, and ASH event heatmap.",
)
async def warehouse(request: Request) -> HTMLResponse:
    """Render the warehouse dashboard page."""
    return templates.TemplateResponse(
        "warehouse/index.html",
        {"request": request, "active_page": "warehouse"},
    )


@router.get(
    "/api/warehouse/udc-hourly",
    summary="UDC hourly missions",
    description="Proxies /udc_hourly_missions from the warehouse API. Returns all UDC mission records with dt_start and mission type.",
)
async def udc_hourly() -> JSONResponse:
    """Fetch today's UDC hourly mission records from the warehouse API."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_WH_API}/udc_hourly_missions")
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@router.get(
    "/api/warehouse/udc-summary",
    summary="UDC summary by date range",
    description="Proxies /udc_summary/ from the warehouse API. Returns daily Entry/Exit/Entry-1/Entry-5 counts.",
)
async def udc_summary(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> JSONResponse:
    """Fetch UDC daily summary for a date range."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_WH_API}/udc_summary",
                params={"start": start, "end": end},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@router.get(
    "/api/warehouse/ash-summary",
    summary="ASH event summary by date range",
    description="Proxies /event_ash_summary from the warehouse API. Returns event_date, description, total_count rows.",
)
async def ash_summary(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
) -> JSONResponse:
    """Fetch ASH event summary for a date range."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_WH_API}/event_ash_summary",
                params={"start_date": start_date, "end_date": end_date},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@router.get(
    "/api/warehouse/ash-descriptions",
    summary="ASH event description catalog",
    description="Proxies /event_ash_descriptions from the warehouse API. Returns full list of known ASH event descriptions.",
)
async def ash_descriptions() -> JSONResponse:
    """Fetch the complete ASH event description catalog."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_WH_API}/event_ash_descriptions",
                params={"last_n_days": 365},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
