"""Response schemas for In CMA not in AS400 report uploads."""

from datetime import datetime

from pydantic import BaseModel


class InCmaNotInAs400UploadResponse(BaseModel):
    """Response returned after report rows are stored in MySQL."""

    filename: str
    report_datetime: datetime
    parsed_rows: int
    inserted_rows: int
    message: str
