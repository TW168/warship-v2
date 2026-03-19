"""
schemas/shipping_status.py — Pydantic models for shipping_status CRUD endpoints.
"""

from datetime import date as date_type

from pydantic import BaseModel, Field


class ShippingStatusBase(BaseModel):
    """Shared fields for shipping_status rows."""

    date: date_type = Field(..., description="Shipping status date")
    customer: float | None = Field(default=None, description="Customer value")
    con_hou: float | None = Field(default=None, description="Con_Hou value")
    con_rem: float | None = Field(default=None, description="Con_Rem value")
    con_pho: float | None = Field(default=None, description="Con_PHO value")
    con_cha: float | None = Field(default=None, description="Con_CHA value")
    total: float | None = Field(default=None, description="Total value")
    hou_ship: float | None = Field(default=None, description="Hou_ship value")
    rem_ship: float | None = Field(default=None, description="Rem_ship value")
    con: float | None = Field(default=None, description="Con value")


class ShippingStatusCreateRequest(ShippingStatusBase):
    """Request body for creating a shipping_status row."""


class ShippingStatusUpdateRequest(ShippingStatusBase):
    """Request body for updating a shipping_status row."""


class ShippingStatusRow(ShippingStatusBase):
    """One shipping_status row returned by the API."""

    id: int = Field(..., description="Primary key")


class ShippingStatusDeleteResponse(BaseModel):
    """Delete response payload."""

    deleted_id: int = Field(..., description="Deleted primary key")
    message: str = Field(..., description="Status message")
