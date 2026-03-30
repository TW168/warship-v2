"""
schemas/top_customers.py — Pydantic models for the Top N Customer Tree Map endpoint.
"""

from pydantic import BaseModel
from typing import List

class CustomerTreeMapItem(BaseModel):
    customer_name: str
    total_weight: float
    total_freight: float
    shipment_count: int

class TopCustomersResponse(BaseModel):
    items: List[CustomerTreeMapItem]
