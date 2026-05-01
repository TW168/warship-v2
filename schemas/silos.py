"""
schemas/silos.py — Pydantic request/response models for the Silos domain.

Covers anomaly event workflow management.  Inventory and consumption data
are returned as raw dicts via JSONResponse (no fixed response_model needed
because the column set is driven by SQL aggregates).
"""

from typing import Optional

from pydantic import BaseModel


class SiloAnomalyStatusUpdateRequest(BaseModel):
    """Request body for updating an anomaly event workflow status.

    Attributes:
        status: New status value — must be 'open', 'acknowledged', or 'closed'.
        notes:  Optional free-text analyst notes to attach to the event.
    """

    status: str
    notes: Optional[str] = None
