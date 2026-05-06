"""
routers/maintenance/shipment_scan.py — Shipment Scan upload and management.

Handles shipment scan document uploads and processing:
- Upload Excel, CSV, or other shipment scan files
- Process and store shipment scan data in database
- Basic CRUD operations for manual data entry

Routes:
    GET    /shipment-scan              — Shipment scan management page
    POST   /api/shipment-scan/upload   — Upload shipment scan files
    GET    /api/shipment-scan          — List shipment scan records
"""

import io
from datetime import datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from logging_config import get_router_logger
from schemas.shipment_scan import (
    ShipmentScanListResponse,
    ShipmentScanUploadResponse,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# One shared engine for this module (created at import time)
_engine = connect_to_database()
logger = get_router_logger("maintenance.shipment_scan")

# Column mapping for flexible Excel/CSV parsing
# Maps common column names to our database columns
_COLUMN_MAPPING = {
    # Tracking identifiers (expanded to catch more variations)
    'tracking number': 'tracking_number',
    'tracking_number': 'tracking_number', 
    'tracking id': 'tracking_number',
    'track': 'tracking_number',
    'shipment id': 'shipment_id',
    'shipment_id': 'shipment_id',
    'order number': 'order_number',
    'order_number': 'order_number',
    'order id': 'order_number',
    'bol': 'bol_number',
    'bol number': 'bol_number',
    'bill of lading': 'bol_number',
    'container': 'container_number',
    'container number': 'container_number',
    
    # Handle cases where large numbers might be in "pallet" or "count" fields
    # but are actually tracking numbers
    'pallet id': 'tracking_number',
    'pallet number': 'tracking_number', 
    'item id': 'tracking_number',
    'item number': 'tracking_number',
    'scan id': 'tracking_number',
    'barcode': 'tracking_number',
    
    # Dates
    'ship date': 'ship_date',
    'shipped date': 'ship_date',
    'delivery date': 'delivery_date',
    'delivered date': 'delivery_date',
    'scan date': 'scan_date',
    'scanned date': 'scan_date',
    'date': 'scan_date',
    
    # Locations
    'origin': 'origin',
    'from': 'origin',
    'destination': 'destination',
    'to': 'destination',
    'current location': 'current_location',
    'location': 'current_location',
    
    # Package details - only for actual small counts
    'weight': 'weight',
    'wt': 'weight',
    'actual pallet count': 'pallet_count',  # More specific
    'pallets': 'pallet_count', 
    'package count': 'package_count',
    'packages': 'package_count',
    'qty': 'package_count',
    'quantity': 'package_count',
    
    # Status and carrier
    'status': 'status',
    'carrier': 'carrier',
    'service': 'service_type',
    'service type': 'service_type',
    
    # Customer info
    'shipper': 'shipper',
    'from company': 'shipper',
    'consignee': 'consignee', 
    'to company': 'consignee',
    
    # References
    'reference': 'reference_1',
    'ref 1': 'reference_1',
    'reference 1': 'reference_1',
    'ref 2': 'reference_2', 
    'reference 2': 'reference_2',
    'notes': 'notes',
    'comments': 'notes',
}

def _normalize_column_name(col_name: str) -> str:
    """Normalize column name for mapping lookup."""
    if not col_name:
        return ''
    return str(col_name).lower().strip()

def _parse_date_value(value):
    """Parse a date value from Excel/CSV."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, 'date'):
        return value.date()
    # Try to parse string dates
    if isinstance(value, str):
        import re
        # Handle common date formats
        date_patterns = [
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
            r'(\d{1,2})/(\d{1,2})/(\d{2})',  # MM/DD/YY
        ]
        for pattern in date_patterns:
            match = re.match(pattern, value.strip())
            if match:
                try:
                    if len(match.group(3)) == 2:  # YY format
                        year = 2000 + int(match.group(3))
                        month, day = int(match.group(1)), int(match.group(2))
                    else:  # YYYY format or YYYY-MM-DD
                        if pattern.startswith(r'(\d{4})'):  # YYYY-MM-DD
                            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        else:  # MM/DD/YYYY
                            month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    return datetime(year, month, day).date()
                except (ValueError, TypeError):
                    continue
    return None

def _parse_numeric_value(value, column_name=None):
    """Parse a numeric value from Excel/CSV."""
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)):
            return int(value) if isinstance(value, float) and value.is_integer() else value
        if isinstance(value, str):
            # Clean up common formatting
            cleaned = value.replace(',', '').replace('$', '').strip()
            if cleaned:
                # Try to return as integer if it's a whole number
                float_val = float(cleaned)
                return int(float_val) if float_val.is_integer() else float_val
    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to parse numeric value '{value}' for column '{column_name}': {e}")
    return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_excel_file(content: bytes, filename: str) -> list[dict]:
    """Parse Excel file content and return list of properly mapped record dictionaries."""
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    ws = wb.active
    
    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = list(next(rows_iter))
    
    print(f"Raw Excel headers: {raw_headers}")
    
    # Normalize and map headers to database columns
    header_mapping = {}
    for i, header in enumerate(raw_headers):
        if header is not None:
            normalized = _normalize_column_name(str(header))
            db_col = _COLUMN_MAPPING.get(normalized)
            if db_col:
                header_mapping[i] = db_col
                print(f"Mapped column {i}: '{header}' -> '{db_col}'")
            else:
                # For unmapped columns, try to find partial matches
                for pattern, db_col in _COLUMN_MAPPING.items():
                    if pattern in normalized or normalized in pattern:
                        header_mapping[i] = db_col
                        print(f"Partial match column {i}: '{header}' -> '{db_col}' (via '{pattern}')")
                        break
                else:
                    print(f"Unmapped column {i}: '{header}' (normalized: '{normalized}')")
    
    print(f"Final column mapping: {header_mapping}")
    
    records = []
    row_count = 0
    for raw_row in rows_iter:
        row_count += 1
        if not any(raw_row):  # Skip empty rows
            print(f"Skipping empty row {row_count}")
            continue
        
        if row_count <= 3:  # Debug first few rows
            print(f"Processing row {row_count}: {raw_row}")
        
        # Create record with mapped columns
        record = {
            'uploaded_at': datetime.now(),
            'source_file': filename,
        }
        
        # Map Excel columns to database columns
        for col_index, db_column in header_mapping.items():
            if col_index < len(raw_row):
                raw_value = raw_row[col_index]
                
                # Parse based on column type
                if db_column in ['ship_date', 'delivery_date', 'scan_date']:
                    record[db_column] = _parse_date_value(raw_value)
                elif db_column in ['weight', 'package_count', 'pallet_count']:
                    record[db_column] = _parse_numeric_value(raw_value, db_column)
                else:
                    # String fields
                    record[db_column] = str(raw_value).strip() if raw_value is not None else None
        
        if row_count <= 3:  # Debug first few parsed records
            print(f"Parsed record {row_count}: {record}")
        
        records.append(record)
    
    print(f"Total records parsed: {len(records)}")
    wb.close()
    return records


def _parse_csv_file(content: bytes, filename: str) -> list[dict]:
    """Parse CSV file content and return list of properly mapped record dictionaries."""
    import csv
    import io as text_io
    
    # Decode bytes to string
    text_content = content.decode('utf-8-sig')  # Handle BOM if present
    csv_reader = csv.DictReader(text_io.StringIO(text_content))
    
    # Map CSV headers to database columns
    header_mapping = {}
    if csv_reader.fieldnames:
        for csv_header in csv_reader.fieldnames:
            normalized = _normalize_column_name(csv_header)
            db_col = _COLUMN_MAPPING.get(normalized)
            if db_col:
                header_mapping[csv_header] = db_col
            else:
                # Try partial matches
                for pattern, db_col in _COLUMN_MAPPING.items():
                    if pattern in normalized or normalized in pattern:
                        header_mapping[csv_header] = db_col
                        break
    
    print(f"CSV column mapping: {header_mapping}")
    print(f"CSV headers: {csv_reader.fieldnames}")
    
    records = []
    for row in csv_reader:
        if not any(row.values()):  # Skip empty rows
            continue
        
        # Create record with mapped columns  
        record = {
            'uploaded_at': datetime.now(),
            'source_file': filename,
        }
        
        # Map CSV columns to database columns
        for csv_col, db_col in header_mapping.items():
            raw_value = row.get(csv_col)
            
            # Parse based on column type
            if db_col in ['ship_date', 'delivery_date', 'scan_date']:
                record[db_col] = _parse_date_value(raw_value)
            elif db_col in ['weight', 'package_count', 'pallet_count']:
                record[db_col] = _parse_numeric_value(raw_value, db_col)
            else:
                # String fields
                record[db_col] = str(raw_value).strip() if raw_value is not None else None
        
        records.append(record)
    
    return records


def _ensure_shipment_scan_table_exists():
    """Ensure the shipment_scan table exists in the database with proper columns."""
    with _engine.connect() as conn:
        # Check if table exists and what columns it has
        try:
            result = conn.execute(text("DESCRIBE shipment_scan")).fetchall()
            print(f"Current table structure: {result}")
            
            # Check if pallet_count is BIGINT
            pallet_count_info = None
            for row in result:
                if row[0] == 'pallet_count':
                    pallet_count_info = row
                    break
            
            if pallet_count_info and 'bigint' not in pallet_count_info[1].lower():
                print(f"pallet_count is {pallet_count_info[1]}, need to recreate table")
                # Drop and recreate if pallet_count is not BIGINT
                conn.execute(text("DROP TABLE shipment_scan"))
                conn.commit()
            else:
                print("Table already has correct structure")
                return
                
        except Exception as e:
            print(f"Table doesn't exist or error checking: {e}")
            # Table doesn't exist, will create it
        
        # Create table with actual columns for shipment data
        print("Creating shipment_scan table with BIGINT columns...")
        conn.execute(text("""
            CREATE TABLE shipment_scan (
                id INT AUTO_INCREMENT PRIMARY KEY,
                uploaded_at DATETIME NOT NULL,
                source_file VARCHAR(255) NOT NULL,
                file_size INT,
                
                -- Common shipment tracking fields
                tracking_number VARCHAR(100),
                shipment_id VARCHAR(100),
                order_number VARCHAR(100),
                bol_number VARCHAR(100),
                container_number VARCHAR(100),
                
                -- Dates
                ship_date DATE,
                delivery_date DATE,
                scan_date DATE,
                
                -- Location info  
                origin VARCHAR(255),
                destination VARCHAR(255),
                current_location VARCHAR(255),
                
                -- Package details (BIGINT for large numbers)
                weight DECIMAL(10,2),
                package_count BIGINT,
                pallet_count BIGINT,
                
                -- Status and carrier
                status VARCHAR(100),
                carrier VARCHAR(100),
                service_type VARCHAR(100),
                
                -- Customer info
                shipper VARCHAR(255),
                consignee VARCHAR(255),
                
                -- Additional fields for flexibility
                reference_1 VARCHAR(255),
                reference_2 VARCHAR(255),
                notes TEXT,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Indexes
                INDEX idx_tracking (tracking_number),
                INDEX idx_source (source_file),
                INDEX idx_scan_date (scan_date),
                INDEX idx_status (status)
            )
        """))
        
        conn.commit()
        print("Table created successfully with BIGINT columns")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/shipment-scan",
    response_class=HTMLResponse,
    summary="Shipment Scan management page",
    description="Upload and manage shipment scan documents and data.",
)
async def shipment_scan_page(request: Request) -> HTMLResponse:
    """Render the shipment scan upload and management page."""
    return templates.TemplateResponse(
        "maintenance/shipment_scan.html",
        {"request": request, "active_page": "shipment_scan"},
    )


@router.post(
    "/api/shipment-scan/upload",
    response_model=ShipmentScanUploadResponse,
    summary="Upload shipment scan file",
    description="Upload and process Excel or CSV shipment scan files.",
)
async def upload_shipment_scan(file: UploadFile = File(...)) -> JSONResponse:
    """Upload and process shipment scan file."""
    if not file.filename:
        return JSONResponse(
            status_code=400,
            content={"error": "No filename provided."}
        )
    
    # Check file extension
    filename_lower = file.filename.lower()
    if not filename_lower.endswith(('.xlsx', '.xls', '.csv')):
        return JSONResponse(
            status_code=422,
            content={"error": "Only Excel (.xlsx, .xls) and CSV files are accepted."}
        )
    
    try:
        content = await file.read()
        file_size = len(content)
        
        # Ensure table exists first
        _ensure_shipment_scan_table_exists()
        
        # Check for duplicate uploads
        with _engine.connect() as conn:
            duplicate_check = conn.execute(
                text("""
                    SELECT 1 FROM shipment_scan 
                    WHERE source_file = :filename AND file_size = :size 
                    LIMIT 1
                """),
                {"filename": file.filename, "size": file_size}
            ).fetchone()
            
            if duplicate_check:
                return JSONResponse(
                    content={"status": "duplicate", "message": "File already uploaded", "rows_inserted": 0}
                )
        
        # Parse file based on extension
        if filename_lower.endswith(('.xlsx', '.xls')):
            records = _parse_excel_file(content, file.filename)
        elif filename_lower.endswith('.csv'):
            records = _parse_csv_file(content, file.filename)
        else:
            return JSONResponse(
                status_code=422,
                content={"error": "Unsupported file format."}
            )
        
        if not records:
            return JSONResponse(
                content={"status": "ok", "message": "No data rows found", "rows_inserted": 0}
            )
        
        # Insert records into proper columns
        with _engine.connect() as conn:
            if records:
                print(f"Preparing to insert {len(records)} records")
                
                # Get all possible columns that might be in our records
                all_columns = set(['uploaded_at', 'source_file', 'file_size'])
                for record in records:
                    all_columns.update(record.keys())
                
                # Remove metadata columns and ensure no duplicates
                data_columns = sorted(all_columns - {'uploaded_at', 'source_file', 'file_size'})
                
                print(f"Data columns found: {data_columns}")
                
                # Build dynamic INSERT statement
                column_list = ['uploaded_at', 'source_file', 'file_size'] + data_columns
                placeholders = [f':{col}' for col in column_list]
                
                insert_sql = text(f"""
                    INSERT INTO shipment_scan ({', '.join(column_list)})
                    VALUES ({', '.join(placeholders)})
                """)
                
                print(f"Insert SQL: {insert_sql}")
                
                # Prepare data for insertion
                insert_data = []
                for i, record in enumerate(records):
                    row_data = {
                        'uploaded_at': record.get('uploaded_at'),
                        'source_file': record.get('source_file'), 
                        'file_size': file_size,
                    }
                    # Add all the parsed shipment data
                    for col in data_columns:
                        row_data[col] = record.get(col)
                    
                    if i < 2:  # Debug first two insert records
                        print(f"Insert data row {i}: {row_data}")
                    
                    insert_data.append(row_data)
                
                try:
                    result = conn.execute(insert_sql, insert_data)
                    conn.commit()
                    print(f"Successfully inserted {result.rowcount} records")
                except Exception as e:
                    print(f"Insert failed: {e}")
                    raise
            else:
                print("No records to insert")
            
            conn.commit()
        
        return JSONResponse(
            content={
                "status": "ok", 
                "message": f"Successfully processed {file.filename}", 
                "rows_inserted": len(records)
            }
        )
        
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Upload failed: {str(exc)}"}
        )


@router.get(
    "/api/shipment-scan",
    response_model=ShipmentScanListResponse,
    summary="List shipment scan records",
    description="Retrieve shipment scan records with optional filters.",
)
async def list_shipment_scan(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records to return"),
    offset: int = Query(default=0, ge=0, description="Number of records to skip"),
    source_file: Optional[str] = Query(default=None, description="Filter by source filename"),
) -> JSONResponse:
    """List shipment scan records with optional pagination and filtering."""
    try:
        # Ensure table exists
        _ensure_shipment_scan_table_exists()
        
        with _engine.connect() as conn:
            # Build query with optional filters
            where_clauses = []
            params = {"limit": limit, "offset": offset}
            
            if source_file:
                where_clauses.append("source_file LIKE :source_file")
                params["source_file"] = f"%{source_file}%"
            
            where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            
            # Get records with actual columns
            query = text(f"""
                SELECT 
                    id, uploaded_at, source_file, file_size, created_at,
                    tracking_number, shipment_id, order_number, bol_number, container_number,
                    ship_date, delivery_date, scan_date,
                    origin, destination, current_location,
                    weight, package_count, pallet_count,
                    status, carrier, service_type,
                    shipper, consignee,
                    reference_1, reference_2, notes
                FROM shipment_scan
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """)
            
            rows = conn.execute(query, params).fetchall()
            
            # Get total count
            count_query = text(f"SELECT COUNT(*) as total FROM shipment_scan{where_sql}")
            count_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}
            total = conn.execute(count_query, count_params).scalar()
        
        records = []
        for row in rows:
            records.append({
                "id": row.id,
                "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
                "source_file": row.source_file,
                "file_size": row.file_size,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                # Shipment data fields
                "tracking_number": row.tracking_number,
                "shipment_id": row.shipment_id,
                "order_number": row.order_number,
                "bol_number": row.bol_number,
                "container_number": row.container_number,
                "ship_date": row.ship_date.isoformat() if row.ship_date else None,
                "delivery_date": row.delivery_date.isoformat() if row.delivery_date else None,
                "scan_date": row.scan_date.isoformat() if row.scan_date else None,
                "origin": row.origin,
                "destination": row.destination,
                "current_location": row.current_location,
                "weight": float(row.weight) if row.weight else None,
                "package_count": row.package_count,
                "pallet_count": row.pallet_count,
                "status": row.status,
                "carrier": row.carrier,
                "service_type": row.service_type,
                "shipper": row.shipper,
                "consignee": row.consignee,
                "reference_1": row.reference_1,
                "reference_2": row.reference_2,
                "notes": row.notes,
            })
        
        return JSONResponse({
            "records": records,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
        
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to retrieve records: {str(exc)}"}
        )