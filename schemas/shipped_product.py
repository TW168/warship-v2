"""
schemas/shipped_product.py — Pydantic models for the shipped-products endpoint.
"""

import datetime
from pydantic import BaseModel


class ShippedProductRow(BaseModel):
    """One aggregated shipment row returned by sp_get_all_shipped_product."""

    bl_number: str
    truck_appointment_date: datetime.date
    site: str
    product_group: str
    product_code: str
    unit_freight: float | None
    carrier_id: str | None
    pallet_count: int | None
    pick_weight: int | None
