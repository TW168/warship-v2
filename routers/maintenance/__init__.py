"""
routers/maintenance/__init__.py — Maintenance section package router.

This module is the single entry point for all ``/maintenance`` routes.
It creates one parent ``APIRouter`` with the ``/maintenance`` prefix and
includes each domain sub-module's router.

Domain → module mapping
-----------------------
Shipping Status CRUD    →  shipping_status.py
Freight Audit           →  freight_audit.py
Closed Complaints       →  closed_complaints.py
Shipment Size Impact    →  shipment_size_impact.py
LMI Document Analysis   →  lmi.py
Truck Load Map          →  truck_load_map.py
Not-in-XFCMA           →  not_in_xfcma.py
Shipment Scan          →  shipment_scan.py
Sales Summary          →  sales_summary.py
Silos (page + ETL + ML) →  silos/   (sub-package)

Usage in main.py (unchanged from pre-refactor):
    from routers import maintenance
    app.include_router(maintenance.router)
"""

from fastapi import APIRouter

from . import (
    closed_complaints,
    freight_audit,
    freight_driver,
    lmi,
    not_in_xfcma,
    sales_summary,
    shipment_scan,
    shipment_size_impact,
    shipping_status,
    truck_load_map,
    work_order_upload,
)
from .silos import router as _silos_router

# Parent router — every route in every sub-module is served under /maintenance
router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

router.include_router(shipping_status.router)
router.include_router(freight_audit.router)
router.include_router(closed_complaints.router)
router.include_router(shipment_size_impact.router)
router.include_router(freight_driver.router)
router.include_router(lmi.router)
router.include_router(truck_load_map.router)
router.include_router(not_in_xfcma.router)
router.include_router(shipment_scan.router)
router.include_router(sales_summary.router)
router.include_router(work_order_upload.router)
router.include_router(_silos_router)

__all__ = ["router"]
