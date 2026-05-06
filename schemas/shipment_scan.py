"""
schemas/shipment_scan.py — Pydantic models for shipment scan API.

Request/response models for the shipment scan endpoints in
``routers/maintenance/shipment_scan.py``.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ShipmentScanRecord(BaseModel):
    """Response model for a single shipment scan record."""
    
    id: int = Field(..., description="Unique record ID")
    uploaded_at: Optional[datetime] = Field(None, description="Upload timestamp")
    source_file: str = Field(..., description="Original filename")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    created_at: Optional[datetime] = Field(None, description="Record creation timestamp")
    
    # Shipment tracking fields
    tracking_number: Optional[str] = Field(None, description="Tracking or reference number")
    shipment_id: Optional[str] = Field(None, description="Shipment ID")
    order_number: Optional[str] = Field(None, description="Order number")
    bol_number: Optional[str] = Field(None, description="Bill of lading number")
    container_number: Optional[str] = Field(None, description="Container number")
    
    # Date fields
    ship_date: Optional[date] = Field(None, description="Ship date")
    delivery_date: Optional[date] = Field(None, description="Delivery date")
    scan_date: Optional[date] = Field(None, description="Scan date")
    
    # Location fields
    origin: Optional[str] = Field(None, description="Origin location")
    destination: Optional[str] = Field(None, description="Destination location")
    current_location: Optional[str] = Field(None, description="Current location")
    
    # Package details
    weight: Optional[float] = Field(None, description="Weight")
    package_count: Optional[int] = Field(None, description="Number of packages")
    pallet_count: Optional[int] = Field(None, description="Number of pallets")
    
    # Status and carrier
    status: Optional[str] = Field(None, description="Shipment status")
    carrier: Optional[str] = Field(None, description="Carrier name")
    service_type: Optional[str] = Field(None, description="Service type")
    
    # Customer info
    shipper: Optional[str] = Field(None, description="Shipper name")
    consignee: Optional[str] = Field(None, description="Consignee name")
    
    # Additional references
    reference_1: Optional[str] = Field(None, description="Reference 1")
    reference_2: Optional[str] = Field(None, description="Reference 2")
    notes: Optional[str] = Field(None, description="Notes or comments")


class ShipmentScanListResponse(BaseModel):
    """Response model for listing shipment scan records."""
    
    records: list[ShipmentScanRecord] = Field(..., description="List of shipment scan records")
    total: int = Field(..., description="Total number of records matching filters")
    limit: int = Field(..., description="Maximum records returned")
    offset: int = Field(..., description="Number of records skipped")


class ShipmentScanUploadResponse(BaseModel):
    """Response model for file upload operations."""
    
    status: str = Field(..., description="Upload status: 'ok', 'duplicate', or 'error'")
    message: str = Field(..., description="Human-readable status message")
    rows_inserted: int = Field(..., description="Number of records processed from the file")


class ShipmentScanErrorResponse(BaseModel):
    """Response model for error cases."""
    
    error: str = Field(..., description="Error message describing what went wrong")