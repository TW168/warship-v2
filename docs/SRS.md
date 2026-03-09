# Software Requirements Specification (SRS)

**Project:** Warship — Warehouse and Shipping Management System
**Version:** 1.0
**Date:** 2026-03-06
**Status:** Active Development

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Overall Description](#2-overall-description)
3. [System Architecture](#3-system-architecture)
4. [Functional Requirements](#4-functional-requirements)
5. [API Endpoints](#5-api-endpoints)
6. [Data Model](#6-data-model)
7. [External Integrations](#7-external-integrations)
8. [UI/UX Requirements](#8-uiux-requirements)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Dependencies](#10-dependencies)
11. [Deployment](#11-deployment)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the software requirements for **Warship**, an internal full-stack web application that centralizes warehouse inventory management, shipping logistics, freight analytics, and Truck Service Request (TSR) workflows into a single platform.

### 1.2 Scope

Warship replaces a collection of standalone Streamlit scripts with a unified FastAPI application. It serves both machine-readable JSON API endpoints and browser-rendered HTML pages from a single process.

### 1.3 Definitions

| Term | Definition |
|------|-----------|
| UDC | Unit Distribution Center — warehouse movement unit |
| ASH | Automated Sorting/Handling — warehouse event classification system |
| TSR | Truck Service Request — internal ticket for shipment issues |
| IPG EZ | IPG EZ Report — Excel export from the AS/400 shipping system |
| BL | Bill of Lading — shipping document number |
| FTL | Full Truckload |
| LTL | Less-Than-Truckload |
| HTMX | HTML-over-the-wire library for partial page updates |

---

## 2. Overall Description

### 2.1 Product Perspective

Warship is an internal web application accessed by warehouse supervisors, shipping coordinators, and operations managers within the CFP organization. It connects to a shared MySQL database (`warship` schema) at `172.17.15.228:3306` and proxies data from the warehouse operations API at `172.17.15.228:8000`.

### 2.2 User Classes

| User Class | Description |
|-----------|-------------|
| Warehouse Operators | View UDC activity, ASH event heatmaps |
| Shipping Coordinators | Run meeting reports, prepare TSR shipment maps |
| Operations Managers | View briefings, freight analytics, weight trends |
| Administrators | Upload IPG EZ Excel reports, view software architecture |

### 2.3 Operating Environment

- **Server:** Linux host, Python 3.12+, port `8088`
- **Browser:** Modern Chromium-based browser (internal use)
- **Database:** MySQL 8.x at `172.17.15.228:3306`, schema `warship`
- **Warehouse API:** FastAPI service at `http://172.17.15.228:8000`

---

## 3. System Architecture

### 3.1 Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI (Python) |
| Template Engine | Jinja2 |
| Frontend Framework | Bootstrap 5 |
| Interactivity | HTMX (partial updates), Plotly.js (charts), Google Maps JS API (maps) |
| ORM / DB Driver | SQLAlchemy + `mysql-connector-python` |
| HTTP Client | `httpx` (async, for proxying warehouse API) |
| Package Manager | `uv` |

### 3.2 Request Flow

```
Browser
  │
  ├── GET /page          → FastAPI router → Jinja2 template → HTML response
  ├── GET /api/endpoint  → FastAPI router → SQLAlchemy / httpx → JSON response
  └── POST /api/upload   → FastAPI router → openpyxl → SQLAlchemy → JSON response
                                                │
                                          MySQL (warship)
                                          Warehouse API (172.17.15.228:8000)
```

### 3.3 Directory Structure

```
warship-v2/
├── main.py              # App factory — registers all routers
├── database.py          # connect_to_database() → SQLAlchemy Engine
├── pyproject.toml       # uv dependency manifest
├── uv.lock              # Committed lockfile for reproducible builds
├── .env                 # Secrets (gitignored) — GOOGLE_MAPS_API_KEY
├── Dockerfile           # Container build (optional deployment path)
├── deploy.sh            # Docker build + run helper script
├── routers/             # One file per feature domain
├── templates/           # Jinja2 HTML templates (mirrors router structure)
├── schemas/             # Pydantic request/response models
├── static/assets/       # Weather images (MaxT1_conus.png, national_forecast.jpg)
├── raw_data/            # Excel workbooks for freight analytics
│   ├── Mei/             # AMJK Frt cost breakdown by plants.xlsx
│   └── John/            # Transp Type.xlsx
├── docs/                # Documentation (architectural.md, SRS.md)
└── tests/               # pytest test suite
```

---

## 4. Functional Requirements

### 4.1 Home Page (`GET /`)

- Display two weather forecast images side-by-side:
  - MaxT1 CONUS temperature map (`MaxT1_conus.png`)
  - National weather forecast (`national_forecast.jpg`)
- Images served via `/weather/maxt1` and `/weather/national` with `Cache-Control: no-store` headers
- Images refreshed daily via cron at 06:00 via `wget` from NOAA/NWS URLs

### 4.2 Meeting Report (`GET /meeting-report`)

- Display a filter form with fields: Site, Product Group, Truck Appointment Date
- On Apply, send HTMX request to `/api/meeting-report/results` and inject result cards
- Result cards show aggregated metrics per customer group (Houston, Remington, Phoenix, Charlotte, Customers)
- Metrics per group: Pallets, Weight (lbs), Freight ($), Avg Freight/lb
- Summary counts shown: Consignment trucks, Custom trucks (excluding SAIA-IP and CWF-IP carriers)
- Data source: `warship.vw_bl_lbs_cnt_carrier_customer` view

### 4.3 Briefing (`GET /briefing`)

- Display a printable VIP Operations Briefing page
- Snapshot of operations metrics for management visits
- Page must render cleanly when printed (`@media print`)

### 4.4 Warehouse Dashboard (`GET /warehouse`)

#### 4.4.1 Today Hourly UDC Chart

- Fetch data from `/api/warehouse/udc-hourly` (proxied from warehouse API)
- Filter records to current date only (client-side by `dt_start` field)
- Group by hour × mission type, render as Plotly.js grouped bar chart
- X-axis: hour (`HH:00`), Y-axis: count, series: mission type
- Show loading spinner in card header; display error alert on failure

#### 4.4.2 UDC History Chart

- Date range pickers (default: last 30 days)
- Fetch data from `/api/warehouse/udc-summary?start=&end=`
- Render as Plotly.js multi-line chart
- Series: Entry, Exit, Entry-1, Entry-5
- Apply button triggers fetch; spinner shown during load

#### 4.4.3 ASH Event Heatmap

- Date range pickers (default: last 30 days)
- Fetch data from `/api/warehouse/ash-summary?start_date=&end_date=`
- Client-side pivot: description × event_date → total_count
- Normalize descriptions (collapse whitespace) before pivoting
- Render as Plotly.js heatmap (colorscale: Blues, reversed)
- Dynamic chart height: `max(400, num_descriptions × 22 + 80)` px
- Note footer: data shift occurred approx. Nov 3–6, 2024

### 4.5 Shipping (`GET /shipping`)

- Placeholder page (to be defined)

### 4.6 TSR Prep (`GET /tsr-prep`)

#### 4.6.1 Excel Upload

- Accept multipart file upload (`.xlsx` / `.xls` only)
- Extract `rpt_run_date` and `rpt_run_time` from filename using regex:
  `r"as of (\d{4}-\d{1,2}-\d{1,2})\s+(\d+)#(\d+)"`
- Duplicate check: `SELECT 1 FROM ipg_ez WHERE file_name=:fn AND file_size=:fs`
- Parse with `openpyxl`; rename columns per `_RENAME` mapping; drop rows where `BL_Number` is null
- Coerce numeric columns (`Pick_Weight`, `Number_of_Pallet`, `Freight_Amount`, `Unit_Freight`) to float/int; fill nulls with 0
- Null out `Truck_Appt_Time` values that are not `datetime.time` or `datetime.datetime` (e.g., string `'N/A'`)
- Bulk INSERT into `warship.ipg_ez`
- Return `{"status": "ok"|"duplicate", "rows_inserted": N}` as JSON
- All processing wrapped in try/except; return `{"error": ...}` with HTTP 500 on failure (never return HTML 500)

#### 4.6.2 Filter Options

- `GET /api/tsr-prep/filter-options` — returns distinct `sites`, `groups`, `dates` from `ipg_ez`
- Auto-populate Site, Product Group, Report Date, Report Time dropdowns on page load

#### 4.6.3 Available-to-Ship List

- `GET /api/tsr-prep/avail-to-ship?site=&group=&date=&time=`
- Query `ipg_ez LEFT JOIN us_cities ON state + city`
- Exclude: BL numbers starting with `WZ`, product codes containing `INSER`, rows with `Truck_Appointment_Date` set
- Aggregate by BL: `SUM(Pick_Weight)`, `SUM(Number_of_Pallet)`
- Return fields: `bl_number`, `csr`, `customer`, `city`, `state`, `wgt`, `plt`, `lat`, `lon`

#### 4.6.4 Ship List Table

- Collapsible via Bootstrap collapse (toggle: summary bar)
- Summary bar shows: total weight (lbs), BL count, Download CSV button
- Table columns: BL Number, Customer, City, State, Weight, Pallets, CSR
- Download CSV includes lat/lon columns

#### 4.6.5 Shipment Map

- Requires `GOOGLE_MAPS_API_KEY` environment variable
- Renders Google Maps with markers for each shipment with valid lat/lon
- Circle overlay per marker with adjustable radius (slider: default 100 mi, range 10–500 mi)
- Nearest-neighbor lines: for each shipment, draw polylines to up to 3 nearest neighbors within radius
- Haversine distance computed client-side (R = 3958.8 mi)
- Marker popup: BL#, Customer, Weight, Pallets
- Map auto-fits bounds to all visible markers

#### 4.6.6 Nearest-Neighbor Distance Table

- Collapsible via Bootstrap collapse (toggle: distance bar)
- Shows: BL#, Customer, Neighbor BL#, Neighbor Customer, Distance (mi)
- Sorted by distance ascending
- Hidden when no neighbors exist within radius

### 4.7 Maintenance Input (`GET /maintenance/input`)

- Form-based data input page (to be defined)

### 4.8 Software Architectural (`GET /maintenance/architectural`)

- Read `docs/architectural.md` and render to HTML with Pygments syntax highlighting
- JS-generated Bootstrap scrollspy TOC sidebar built from heading elements at page load
- Required sections: Introduction, System Overview, Architectural Styles & Patterns, Technology Stack, Data Model, Folder Structure, API Endpoints, Deployment & Scaling, Security & Compliance, Future Roadmap

### 4.9 About (`GET /about`)

- Informational page about the Warship system (to be defined)

### 4.10 Health Check (`GET /health`)

- Returns: `{"status": "ok", "service": "warship", "version": "0.1.0"}`
- Always returns HTTP 200; used by `deploy.sh` post-deploy verification

---

## 5. API Endpoints

### 5.1 Page Routes (HTML)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Home — weather images |
| GET | `/meeting-report` | Meeting Report filter form |
| GET | `/briefing` | VIP Operations Briefing |
| GET | `/warehouse` | Warehouse dashboard |
| GET | `/shipping` | Shipping page |
| GET | `/tsr-prep` | TSR Prep ship list + map |
| GET | `/maintenance/input` | Maintenance data input |
| GET | `/maintenance/architectural` | Software Architecture document |
| GET | `/about` | About page |

### 5.2 JSON API Routes

| Method | Path | Params | Description |
|--------|------|--------|-------------|
| GET | `/health` | — | Health check |
| GET | `/api/meeting-report/results` | `site`, `product_group`, `date` | HTMX partial: meeting report cards |
| GET | `/api/analytics/weight-by-year` | `site` (AMJK), `product_group` (SW) | Monthly pick_weight per year series |
| GET | `/api/analytics/freight-lbs-by-year-mei` | `site` (SW) | Monthly lbs from `frt_cost_breakdown_mei` |
| GET | `/api/analytics/unit-frt-cost-john` | — | All rows from `unit_frt_cost_john` |
| GET | `/api/analytics/freight-cost-by-plant` | — | Annual YTD freight cost by plant (Excel) |
| GET | `/api/analytics/sw-transport-type-by-year` | — | SW annual lbs by transport type (Excel) |
| GET | `/api/analytics/amjk-frt-ytd-vs-avg` | — | AMJK SW monthly avg vs YTD (Excel) |
| GET | `/api/warehouse/udc-hourly` | — | Proxy: UDC hourly missions |
| GET | `/api/warehouse/udc-summary` | `start`, `end` | Proxy: UDC daily summary by date range |
| GET | `/api/warehouse/ash-summary` | `start_date`, `end_date` | Proxy: ASH event summary by date range |
| GET | `/api/warehouse/ash-descriptions` | — | Proxy: full ASH event description catalog |
| POST | `/api/tsr-prep/upload` | `file` (multipart) | Upload IPG EZ Excel → insert to `ipg_ez` |
| GET | `/api/tsr-prep/filter-options` | — | Distinct sites, groups, dates from `ipg_ez` |
| GET | `/api/tsr-prep/avail-to-ship` | `site`, `group`, `date`, `time` | Available-to-ship rows with lat/lon |

### 5.3 Static Asset Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/weather/maxt1` | MaxT1 CONUS image (no-cache) |
| GET | `/weather/national` | National forecast image (no-cache) |
| GET | `/static/*` | Static files (CSS, JS, images) |

---

## 6. Data Model

### 6.1 MySQL Database: `warship`

#### Table: `ipg_ez`

Stores uploaded IPG EZ report rows. Populated by the TSR Prep upload endpoint.

| Column | Type | Notes |
|--------|------|-------|
| `Site` | VARCHAR | e.g., `CFP`, `AMJK` |
| `BL_Number` | VARCHAR | Bill of Lading number; rows without this are dropped |
| `Truck_Appointment_Date` | DATE | NULL = available to ship |
| `BL_Weight` | FLOAT | |
| `Freight_Amount` | FLOAT | |
| `Truck_Appt_Time` | TIME | NULL for non-appointment rows (e.g., original `'N/A'` strings) |
| `Pickup_Date` | DATE | |
| `State` | VARCHAR(2) | US state abbreviation |
| `Ship_to_City` | VARCHAR | |
| `Ship_to_Customer` | VARCHAR | |
| `Order_Number` | VARCHAR | |
| `Order_Item` | VARCHAR | |
| `CSR` | VARCHAR | Customer Service Representative |
| `Freight_Term` | VARCHAR | |
| `Require_Date` | DATE | |
| `Schedule_Date` | DATE | |
| `Unshipped_Weight` | FLOAT | |
| `Product_Code` | VARCHAR | |
| `Pick_Weight` | FLOAT | |
| `Number_of_Pallet` | INT | |
| `Pickup_By` | VARCHAR | |
| `Change_Date` | DATE | |
| `Carrier_ID` | VARCHAR | |
| `Arrange_By` | VARCHAR | |
| `Unit_Freight` | FLOAT | cents per lb |
| `Waybill_Number` | VARCHAR | |
| `Sales_Code` | VARCHAR | |
| `Transportation_Code` | VARCHAR | |
| `Transaction_Type` | VARCHAR | |
| `Product_Group` | VARCHAR | e.g., `SW` |
| `rpt_run_date` | DATE | Parsed from filename |
| `rpt_run_time` | VARCHAR | Parsed from filename, e.g., `"09:00:00"` |
| `file_name` | VARCHAR | Original upload filename |
| `file_size` | BIGINT | Used for duplicate detection |

#### Table: `us_cities`

Reference table for geocoding city/state pairs.

| Column | Type | Notes |
|--------|------|-------|
| `city_ascii` | VARCHAR | City name (ASCII) |
| `state_id` | VARCHAR(2) | US state abbreviation |
| `lat` | FLOAT | Latitude |
| `lon` | FLOAT | Longitude |

#### View: `warship.vw_bl_lbs_cnt_carrier_customer`

Aggregated shipping view used by Meeting Report and analytics endpoints.

Key columns: `Site`, `Product_Group`, `Truck_Appointment_Date`, `BL_Number`, `Carrier_ID`, `Ship_to_Customer`, `pick_weight`, `pallet_count`, `Unit_Freight`

#### Table: `frt_cost_breakdown_mei`

Monthly freight cost breakdown imported from MEI data.

| Column | Type | Notes |
|--------|------|-------|
| `site` | VARCHAR | Site/product group code |
| `yyyy` | INT | Year |
| `mm` | INT | Month |
| `lbs` | FLOAT | Weight in lbs |

#### Table: `unit_frt_cost_john`

Unit freight cost tracking by division and product.

| Column | Type |
|--------|------|
| `id` | INT |
| `yyyy` | INT |
| `mm` | INT |
| `division` | VARCHAR |
| `product` | VARCHAR |
| `wt_lbs` | FLOAT |
| `freight` | FLOAT |

### 6.2 Excel Workbooks (raw_data/)

| File | Path | Used By |
|------|------|---------|
| `AMJK Frt cost breakdown by plants.xlsx` | `raw_data/Mei/` | `/api/analytics/freight-cost-by-plant`, `/api/analytics/amjk-frt-ytd-vs-avg` |
| `Transp Type.xlsx` | `raw_data/John/` | `/api/analytics/sw-transport-type-by-year` |

---

## 7. External Integrations

### 7.1 Warehouse Operations API

- **Base URL:** `http://172.17.15.228:8000`
- **Protocol:** HTTP (internal network only)
- **Client:** `httpx.AsyncClient` with 15-second timeout
- **Error handling:** All proxy errors return HTTP 502 `{"error": "..."}`

| Endpoint | Called By |
|----------|-----------|
| `GET /udc_hourly_missions` | `/api/warehouse/udc-hourly` |
| `GET /udc_summary/` | `/api/warehouse/udc-summary` |
| `GET /event_ash_summary` | `/api/warehouse/ash-summary` |
| `GET /event_ash_descriptions` | `/api/warehouse/ash-descriptions` |

### 7.2 Google Maps JavaScript API

- **Key:** `GOOGLE_MAPS_API_KEY` environment variable (from `.env` file)
- **Loaded via:** CDN `<script>` tag with `async defer` and `callback=initMap`
- **Used by:** TSR Prep map (markers, circles, polylines)
- If key is missing, a warning banner is shown in place of the map

### 7.3 NOAA / NWS Weather Images

- Fetched daily at 06:00 via cron (`wget`)
- Stored locally in `static/assets/`
- Served with `Cache-Control: no-store` headers to ensure freshness

### 7.4 Plotly.js

- **Version:** 2.35.2
- **Loaded via:** CDN `<script>` tag
- **Used by:** Warehouse dashboard (3 charts), Briefing analytics

---

## 8. UI/UX Requirements

### 8.1 Design System

| Token | Value |
|-------|-------|
| Primary color | IBM Blue `#154e9a` |
| Font | Open Sans (Google Fonts) |
| Framework | Bootstrap 5 |
| Icons | Bootstrap Icons (`bi-*`) only |

### 8.2 Layout Rules

- All pages extend `base.html` — never inline a full HTML skeleton
- Page content uses `container` or `container-fluid` with `py-4` vertical padding
- Card depth via `shadow-sm`; avoid heavy borders
- Tables: `table table-striped table-hover table-sm` with sticky `thead`
- Forms: labels above inputs; validation feedback always visible

### 8.3 Interactivity Patterns

| Pattern | Implementation |
|---------|---------------|
| Partial page updates | HTMX (`hx-get`, `hx-target`) |
| Loading state | Bootstrap `spinner-border` during async operations |
| Success/error feedback | Bootstrap Toast (bottom-right); never `alert()` |
| Destructive confirmations | Bootstrap modal; never `confirm()` |
| Collapsible sections | Bootstrap collapse with chevron rotation transition |
| Charts | Plotly.js (transparent background, Open Sans font) |

### 8.4 Responsiveness

- Mobile-first; all layouts must work at 375 px viewport width
- Navbar collapses to hamburger on small screens
- Tables wrap in `table-responsive` where reflow is not possible

### 8.5 Accessibility

- All `<img>` tags must have descriptive `alt` text
- All form inputs must have `<label>` or `aria-label`
- Color must never be the sole differentiator — pair with icon or text

---

## 9. Non-Functional Requirements

### 9.1 Performance

- API responses (DB queries) should complete within 5 seconds under normal load
- Proxy routes to warehouse API use 15-second timeout; surface errors gracefully
- Plotly charts must render client-side without blocking the page

### 9.2 Reliability

- All API endpoints must return JSON on error — never HTML error pages
- DB connection errors must return HTTP 500 with `{"error": "..."}` body
- Proxy errors must return HTTP 502 with `{"error": "..."}` body
- Upload errors must return HTTP 500 with `{"error": "..."}` body (not HTML 500)

### 9.3 Security

- SQL queries use SQLAlchemy parameterized statements (`:param` syntax) — no string interpolation
- File uploads validate extension (`.xlsx`/`.xls`) before processing
- Google Maps API key injected from environment — never hardcoded or committed
- Database credentials are hardcoded per project convention (internal network only)
- `.env` is gitignored; never committed

### 9.4 Maintainability

- Every router function must have a docstring
- Every API endpoint decorator must have `summary` and `description` for Swagger UI
- Use `APIRouter` per domain; never define routes on `app` directly
- CLAUDE.md must be updated when routes, dependencies, or UI patterns change

### 9.5 Observability

- Swagger UI available at `/docs`
- ReDoc available at `/redoc`
- Health check at `/health` for deployment verification

---

## 10. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi[standard]` | latest | Web framework + uvicorn + HTMX support |
| `sqlalchemy` | latest | ORM / database engine |
| `mysql-connector-python` | latest | MySQL driver |
| `httpx` | latest | Async HTTP client for warehouse API proxy |
| `pygments` | latest | Syntax highlighting for architectural page |
| `markdown` | latest | Markdown → HTML for architectural page |
| `openpyxl` | latest | Read `.xlsx` workbooks (analytics + TSR upload) |
| `python-dotenv` | latest | Load `.env` for `GOOGLE_MAPS_API_KEY` |

Frontend (CDN, no pip install):

| Library | Version | Purpose |
|---------|---------|---------|
| Bootstrap 5 | 5.x | UI framework |
| Bootstrap Icons | latest | Icon set |
| HTMX | latest | Partial page updates |
| Plotly.js | 2.35.2 | Charts (warehouse dashboard, briefing) |
| Google Maps JS API | latest | TSR Prep shipment map |

---

## 11. Deployment

### 11.1 Development

```bash
uv sync                                          # Install dependencies
uv run fastapi dev main.py --port 8088           # Start dev server (auto-reload)
export GOOGLE_MAPS_API_KEY=your_key              # Required for TSR map
```

### 11.2 Production (Direct)

```bash
uv run fastapi run main.py --host 0.0.0.0 --port 8088
```

`.env` file is loaded via `load_dotenv(Path(__file__).parent / ".env")` regardless of working directory.

### 11.3 Docker

```bash
./deploy.sh
```

`deploy.sh` performs:
1. Stop + remove existing container and image
2. `docker build -t warship-v2 .`
3. `docker run -d --network host --name warship-v2 --env-file .env warship-v2`
4. `curl http://localhost:8088/health` to verify

The `--env-file .env` flag injects secrets at runtime. The `.env` file is **never baked into the image**.

### 11.4 Scheduled Jobs

```cron
# Daily at 06:00 — refresh weather images from NOAA/NWS
0 6 * * * wget -O /path/to/static/assets/MaxT1_conus.png <NOAA_URL>
0 6 * * * wget -O /path/to/static/assets/national_forecast.jpg <NWS_URL>
```

---

*Last updated: 2026-03-06*
