"""
schemas/tsr_prep.py — Pydantic response models for the TSR Prep endpoints.
"""

from pydantic import BaseModel


class AvailToShipRow(BaseModel):
    """One aggregated row returned by the available-to-ship query."""

    bl_number: str
    csr: str | None = None
    customer: str
    city: str
    state: str
    wgt: float
    plt: int
    lat: float | None = None
    lon: float | None = None
