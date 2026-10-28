"""Pydantic response models for Vision Learning barcode scanning."""

from pydantic import BaseModel, Field


class DetectedBarcode(BaseModel):
    """A barcode value and its detected symbology."""

    value: str
    symbology: str
    x: float
    y: float
    width: float
    height: float


class BarcodeScanResponse(BaseModel):
    """Barcode scan results for one in-memory image upload."""

    filename: str
    barcode_count: int = Field(ge=0)
    barcodes: list[DetectedBarcode]
