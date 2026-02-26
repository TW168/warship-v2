"""
schemas/meeting_report.py — Pydantic models for the Meeting Report endpoint.
"""

from pydantic import BaseModel


class MeetingReportRow(BaseModel):
    """One aggregated row returned by the meeting report query."""

    group: str                      # Customer group label (Houston, Remington, etc.)
    pallets: int | None             # Total pallet count
    weight: float | None            # Total pick weight (lbs)
    freight: float | None           # Total freight cost (dollars)
    avg_freight_per_lb: float | None  # Freight cost per pound (dollars, 4 decimals)
