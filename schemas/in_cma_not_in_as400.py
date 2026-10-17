"""Response schemas for In CMA not in AS400 PDF uploads."""

from pydantic import BaseModel


class InCmaNotInAs400UploadResponse(BaseModel):
    """Response returned after the original PDF has been stored in MySQL."""

    id: int
    filename: str
    size_bytes: int
    message: str
