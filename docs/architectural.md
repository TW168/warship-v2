# Warship — Software Architecture

## Introduction

**Warship** (Warehouse and Shipping Management System) is an internal full-stack web application
designed to centralize warehouse inventory management, shipping logistics, freight analytics, and truck service
request (TSR) workflows into a single, cohesive platform.

This document describes the architectural decisions, technology choices, data model, and
deployment strategy for the Warship application. It is intended as a living reference for
developers and operators maintaining the system.

---

## System Overview

Warship follows a **server-rendered web application** model. The FastAPI backend handles all
routing: some routes return JSON (REST API), while others render Jinja2 HTML templates served
directly to the browser. Client-side interactivity is provided via HTMX (partial DOM updates)
and Plotly.js (interactive charts), with no JavaScript build step required.

```
Browser ──HTTP──► FastAPI (Python 3.12)
                     │
                     ├── HTML routes  → Jinja2 Templates
                     ├── API routes   → JSONResponse
                     └── Static files → /static/*
                             │
                        SQLAlchemy Engine
                        (raw SQL + stored procedures)
                             │
                        MySQL 8.x Database
                             │
                     ┌───────┴────────┐
                     │  Views/Tables  │  Stored Procedures
                     └───────────────┘
```

Background data collection runs independently of the web process:

```
cron (7:30 AM daily)
  └── scripts/scrape_gas_prices.py → gas_prices table
```

---

## Architectural Styles & Patterns

### Router-per-Domain

Each business domain lives in its own `routers/` file. All routers are registered in `main.py`
with a shared prefix. This prevents a monolithic route file and makes it easy to add new domains.

| Router | File | Prefix |
|--------|------|--------|
| Home / Analytics | `routers/home.py` | (none) |
| Warehouse | `routers/warehouse.py` | (none) |
| Shipping | `routers/shipping.py` | (none) |
| TSR Prep | `routers/tsr_prep.py` | (none) |
| Maintenance | `routers/maintenance.py` | `/maintenance` |
| About | `routers/about.py` | (none) |
| Health | `routers/health.py` | (none) |

### Database Access Pattern

The app uses **raw SQL via SQLAlchemy `text()`** and **stored procedures via `callproc()`** —
no ORM model layer. Each router instantiates the engine once at module level:

```python
_engine = connect_to_database()   # reuses connection pool across requests

# Pattern A — parameterized raw SQL
with _engine.connect() as conn:
    result = conn.execute(text("SELECT ... WHERE site = :site"), {"site": site})

# Pattern B — stored procedure (requires unwrapping to raw mysql-connector cursor)
with _engine.connect() as conn:
    raw = conn.connection.driver_connection
    cursor = raw.cursor(dictionary=True)
    cursor.callproc("sp_carrier_cost_per_pound", [date_from, date_to, site, product_group])
    for rs in cursor.stored_results():
        rows = rs.fetchall()
```

### Schema-First API Design

All JSON responses use Pydantic models declared in `schemas/`. JSON-only endpoints that return
heterogeneous or dynamic shapes use `JSONResponse` with manual `float()` / `str()` casting
(SQLAlchemy returns `Decimal` and `datetime` objects that are not JSON-serializable by default).

### HTMX for Partial Rendering

HTMX attributes on HTML elements trigger targeted HTTP requests and swap only the affected DOM
fragment. Used on the Meeting Report page for filter-driven result cards.

### Plotly.js for Charts

Interactive charts (bubble charts, bar charts, box plots) are rendered client-side using
Plotly.js loaded from CDN. Data is fetched from JSON API endpoints via `fetch()`.

---

## Technology Stack

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Web framework | FastAPI | ≥ 0.133 | ASGI, auto OpenAPI, Pydantic v2 |
| ASGI server | Uvicorn | bundled | via `fastapi[standard]` |
| Database abstraction | SQLAlchemy | ≥ 2.0 | Engine + raw SQL (no ORM models) |
| Database | MySQL | 8.x | Primary data store |
| DB driver | mysql-connector-python | ≥ 9.x | Used for both raw SQL and `callproc()` |
| Templating | Jinja2 | bundled | Server-side HTML rendering |
| Frontend framework | Bootstrap 5 | 5.3 | CDN, responsive utilities |
| Icons | Bootstrap Icons | 1.11 | CDN |
| Partial updates | HTMX | 2.x | CDN, no build step |
| Charts | Plotly.js | 2.35.2 | CDN, bubble + bar + box charts |
| HTTP client | httpx | ≥ 0.28 | Async proxy calls to warehouse service; scraper |
| Excel parsing | openpyxl | ≥ 3.1 | Reads `.xlsx` for freight cost analytics |
| HTML parsing | beautifulsoup4 | latest | Gas price scraper |
| Syntax highlighting | Pygments | ≥ 2.19 | Architectural page code blocks |
| Markdown rendering | markdown | ≥ 3.10 | Architectural page source |
| Package manager | uv | latest | Manages `.venv`, replaces pip |

---

## Data Model

### Active Tables

**`gas_prices`** — National average fuel prices scraped daily from AAA

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK AUTO_INCREMENT | Primary key |
| fuel_type | VARCHAR(20) | Regular, Mid-Grade, Premium, Diesel, E85 |
| price | DECIMAL(5,3) | Price per gallon in USD |
| scraped_at | DATETIME | Timestamp of scrape (inserted by cron, never deleted) |

**`amin_daily_shipment_summary`** — Parsed AMIN daily shipment report lines

| Column | Type | Description |
|--------|------|-------------|
| report_generated_at | DATETIME | Printed report date and time; timezone is not identified in the PDF |
| report_name | VARCHAR(255) | Report title as printed in the PDF header |
| page_number, pdf_page_count | INT | Printed page number and actual PDF page count |
| line_number | INT | Row order within a printed page |
| row_type | VARCHAR(10) | `detail` for shipment-date rows; `total` for the printed aggregate |
| ship_date | DATE | Shipment date; null for the aggregate row |
| qty_shipped | BIGINT | Quantity shipped in pounds (unit confirmed by the user for display) |
| shipped_avg | BIGINT | Value as printed; the PDF does not identify its unit |
| freight_total | DECIMAL(15,2) | Freight total as printed; currency is not identified in the PDF |
| avg_frt_cent_lb | DECIMAL(12,4) | Average freight in cents per pound, matching the printed column heading |
| source_file | VARCHAR(255) | Uploaded PDF filename |
| uploaded_at_utc | DATETIME | Upload time recorded in UTC |

**`frt_cost_breakdown_mei`** — Monthly freight cost breakdown (Mei plant)

| Column | Type | Description |
|--------|------|-------------|
| (see DB) | | Read by `/api/analytics/freight-lbs-by-year-mei` |

**`unit_frt_cost_john`** — Unit freight cost data (John plant)

| Column | Type | Description |
|--------|------|-------------|
| id, yyyy, mm, division, product, wt_lbs, freight | | Read by `/api/analytics/unit-frt-cost-john` |

### Active Views

**`vw_bl_lbs_cnt_carrier_customer`** — Central shipping/logistics view. Queried by:
- Meeting Report (`/api/meeting-report/results`)
- Weight by Year (`/api/analytics/weight-by-year`)
- Freight Lbs by Year MEI (`/api/analytics/freight-lbs-by-year-mei`)

### Stored Procedures

| Procedure | Called by | Description |
|-----------|-----------|-------------|
| `sp_get_all_shipped_product` | `/api/shipping/shipped-products` | Aggregated shipments by site, product group, date range |
| `sp_carrier_cost_per_pound` | `/api/carrier-cost-analysis` | Carrier cost per pound breakdown; all params optional |

### External Data Sources

| Source | Used by | Notes |
|--------|---------|-------|
| NOAA (HTTPS) | Weather images | Downloaded by cron at 6 AM daily via `wget` |
| AAA gas prices (HTTPS) | `gas_prices` table | Scraped by cron at 7:30 AM daily |
| Excel workbooks (`raw_data/`) | `/api/analytics/freight-cost-by-plant` | `AMJK Frt cost breakdown by plants-26.02.03.xlsx` |

---

## Folder Structure

```
warship-v2/
├── main.py                  # FastAPI app factory — registers routers, mounts /static
├── database.py              # connect_to_database() → SQLAlchemy Engine (hardcoded creds)
├── pyproject.toml           # uv project metadata and dependencies
├── uv.lock                  # Locked dependency tree for reproducible builds
├── Dockerfile               # Production container (python:3.12-slim + uv)
├── .gitignore
├── README.md
│
├── routers/                 # One APIRouter per domain
│   ├── health.py            # GET /health
│   ├── home.py              # GET /  /meeting-report  /briefing  /api/gas-prices  /api/analytics/*  /weather/*
│   ├── warehouse.py         # GET /warehouse  /api/warehouse/*
│   ├── shipping.py          # GET /shipping  /api/carrier-cost-analysis  /api/shipping/*
│   ├── tsr_prep.py          # GET /tsr-prep
│   ├── maintenance.py       # Maintenance pages and APIs
│   └── about.py             # GET /about
│
├── schemas/                 # Pydantic response/request models
│   ├── health.py            # HealthResponse
│   ├── shipped_product.py   # ShippedProductRow
│   ├── meeting_report.py    # MeetingReportRow
│   └── tsr_prep.py          # AvailToShipRow
│
├── scripts/                 # Standalone background scripts (run by cron)
│   └── scrape_gas_prices.py # Scrapes AAA → inserts into gas_prices table
│
├── templates/               # Jinja2 HTML templates
│   ├── base.html            # Navbar, Bootstrap 5, Open Sans, HTMX
│   ├── home/
│   │   ├── index.html       # Weather maps + gas prices card + quick access
│   │   ├── meeting_report.html
│   │   ├── meeting_report_results.html
│   │   ├── briefing.html
│   ├── warehouse/index.html
│   ├── shipping/index.html  # Filter bar + carrier cost bubble chart + shipped-weight charts
│   ├── tsr_prep/index.html
│   ├── maintenance/
│   └── about/index.html
│
├── static/
│   ├── css/custom.css
│   └── assets/              # MaxT1_conus.png, national_forecast.jpg (refreshed by cron)
│
├── raw_data/                # Excel workbooks for freight analytics
│   ├── Mei/
│   └── John/
│
└── docs/
    ├── architectural.md
    └── SRS.md               # Software Requirements Specification
```

---

## API Endpoints

### System

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| GET | `/health` | JSON | Service health — `{status, service, version}` |
| GET | `/docs` | HTML | Swagger UI |
| GET | `/redoc` | HTML | ReDoc API documentation |

### HTML Pages

| Method | Path | Template | Description |
|--------|------|----------|-------------|
| GET | `/` | `home/index.html` | Weather maps + national gas prices + quick access |
| GET | `/meeting-report` | `home/meeting_report.html` | Filter form (site, product_group, date) |
| GET | `/briefing` | `home/briefing.html` | VIP Operations Briefing — printable ops snapshot |
| GET | `/warehouse` | `warehouse/index.html` | UDC hourly/history charts, ASH event heatmap |
| GET | `/shipping` | `shipping/index.html` | Carrier cost analysis + shipped-weight charts |
| GET | `/tsr-prep` | `tsr_prep/index.html` | Truck Service Request prep dashboard |
| GET | `/maintenance/input` | `maintenance/input.html` | Data entry form |
| GET | `/maintenance/amin-daily-shipment-summary` | `maintenance/amin_daily_shipment_summary.html` | Upload PDFs; select a report year/month to view the latest snapshot's table; monthly chart spans all report months independently |
| GET | `/about` | `about/index.html` | About page |

### JSON API

| Method | Path | Params | Description |
|--------|------|--------|-------------|
| GET | `/api/gas-prices` | — | Latest national avg gas prices from `gas_prices` table; includes comparison to previous scrape date |
| GET | `/api/meeting-report/results` | `site`, `product_group`, `date` | HTMX partial — aggregated shipping cards |
| GET | `/api/analytics/weight-by-year` | `site`, `product_group` | Monthly pick_weight per year series |
| GET | `/api/analytics/freight-lbs-by-year-mei` | `site` | Monthly lbs from `frt_cost_breakdown_mei` |
| GET | `/api/analytics/unit-frt-cost-john` | — | All rows from `unit_frt_cost_john` |
| GET | `/api/analytics/freight-cost-by-plant` | — | Annual YTD freight cost by plant from Excel |
| GET | `/api/carrier-cost-analysis` | `date_from`, `date_to`, `site`, `product_group` | Calls `sp_carrier_cost_per_pound`; returns carrier_id, bl_count, total_weight, total_pallets, total_freight_cost, cost_per_pound |
| GET | `/api/shipping/shipped-products` | `site`, `product_group`, `date_from`, `date_to` | Calls `sp_get_all_shipped_product`; drives boxplot + top-weight charts |
| GET | `/api/warehouse/*` | — | Proxied from warehouse service at `172.17.15.228:8000` via httpx |
| POST | `/maintenance/api/amin-daily-shipment-summary/upload` | Multipart `file` | Parses and stores AMIN shipment details and aggregate; replaces existing lines with the same printed report timestamp |
| GET | `/maintenance/api/amin-daily-shipment-summary/periods` | — | Available report-generation year/month selector values, newest first |
| GET | `/maintenance/api/amin-daily-shipment-summary/data` | `year`, `month` | Latest generated report snapshot for the selected report month, including details and aggregate |
| GET | `/maintenance/api/amin-daily-shipment-summary/monthly-trend` | — | One Qty Shipped (lbs) / average freight point per report year/month, using that month's latest report aggregate |
| GET | `/weather/maxt1` | — | Serves `MaxT1_conus.png` with no-cache headers |
| GET | `/weather/national` | — | Serves `national_forecast.jpg` with no-cache headers |

---

## Deployment & Scaling

### Current: Direct Process (No Container)

The app runs directly on the host machine via uv:

```bash
uv run fastapi dev main.py --port 8088 --host 0.0.0.0
```

### Cron Jobs

| Schedule | Command | Purpose |
|----------|---------|---------|
| `0 6 * * *` | `wget` NOAA URLs → `static/assets/` | Refresh weather map images daily |
| `30 7 * * *` | `.venv/bin/python scripts/scrape_gas_prices.py` | Scrape AAA gas prices → MySQL |

### Docker Build (Future)

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8088"]
```

### Scaling Considerations

- The app is stateless; multiple replicas can run behind a load balancer.
- MySQL connection pooling is handled automatically by SQLAlchemy (`pool_pre_ping=True`, `pool_recycle=1800`).
- Background scraper scripts connect directly to MySQL — keep them on the same host or ensure network access.

---

## Security & Compliance

| Area | Status | Notes |
|------|--------|-------|
| Database credentials | Hardcoded in `database.py` | Acceptable for internal deployment; do not expose publicly |
| HTTPS | Delegated | Handled at the reverse proxy layer |
| Authentication | Not implemented | Planned for a future release |
| Input validation | Pydantic + `text()` params | API inputs validated; SQL uses named parameters to prevent injection |
| SQL injection | Parameterized queries | SQLAlchemy `text()` with named params; `callproc()` with positional params |
| XSS | Jinja2 auto-escape | All template variables auto-escaped by default |
| CSRF | Not implemented | Required when state-changing form POSTs are added |

---

## Future Roadmap

| Feature | Priority | Notes |
|---------|----------|-------|
| User authentication | High | Login/logout, role-based access (admin, operator, viewer) |
| CRUD API endpoints | High | POST/PUT/DELETE for warehouse items, shipments, TSRs |
| HTMX-powered tables | Medium | Live search and pagination without page reloads |
| Email notifications | Medium | Alerts for low stock or shipment status changes |
| Export to CSV/Excel | Medium | Bulk export for warehouse and shipping data |
| Audit log | Low | Track all data changes with user + timestamp |
| Dark mode | Low | Toggle light/dark theme via CSS custom properties |
| Unit and integration tests | Ongoing | pytest coverage for all routes and business logic |
