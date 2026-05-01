"""
routers/maintenance/silos/__init__.py — Silos sub-package router.

Combines the three silo sub-module routers into a single ``router`` object
that the parent maintenance package can include with one call.

Sub-module responsibilities:
    upload.py      — Silos dashboard page + CSV ingest endpoint
    api.py         — Serving-layer inventory and consumption-rate endpoints
    anomaly_api.py — Anomaly event investigation endpoints
"""

from fastapi import APIRouter

from . import upload, api, anomaly_api

# Parent router — no additional prefix; the maintenance package applies /maintenance
router = APIRouter(tags=["Silos"])

router.include_router(upload.router)
router.include_router(api.router)
router.include_router(anomaly_api.router)

__all__ = ["router"]
