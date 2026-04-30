# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Status: Active development** — initial scaffold complete, DB not yet wired to pages.

> **Living document.** This app is actively developed. Every time a new route, model, UI pattern, or architectural decision is added, update the relevant section of this file before finishing the task.

---

## What You Are Building

**Warship** — Warehouse and Shipping Management System

- **Backend:** FastAPI (Python) with SQLAlchemy + MySQL (`mysql-connector-python`)
- **Frontend:** Jinja2 templates with Bootstrap 5
- **Theme:** Light/Professional — White, Gray, IBM Blue (`#154e9a`), Open Sans font
- **Serving:** FastAPI serves both JSON API endpoints and Jinja2-rendered HTML templates

---

## Development Commands

```bash
# Create venv and install all dependencies (first time or after pulling)
uv sync

# Run the development server (uses .venv automatically)
uv run fastapi dev main.py --port 8088

# Add a package
uv add <package>

# Run a single test
uv run pytest tests/test_health.py -v

# Run all tests
uv run pytest
```

> `uv` manages the `.venv` automatically — never activate it manually or use `pip`.
> In VSCode: **Ctrl+Shift+P → Python: Select Interpreter → choose `.venv`**

---

## Project Structure Convention

```
warship-v2/
├── main.py                  # FastAPI app factory, mounts routers
├── database.py              # connect_to_database() engine factory
├── pyproject.toml           # uv-managed dependencies and project metadata
├── uv.lock                  # committed — ensures reproducible builds on Dokploy
├── .venv/                   # local venv created by uv (gitignored)
├── .gitignore
├── Dockerfile               # for Dokploy deployment
├── README.md
├── .github/
│   └── workflows/           # CI (optional, Dokploy auto-deploys from GitHub push)
├── routers/
│   ├── health.py            # GET /health
│   ├── home.py              # GET /, /meeting-report, /briefing
│   ├── warehouse.py
│   ├── shipping.py
│   ├── tsr_prep.py
│   ├── maintenance.py       # Maintenance APIs and pages
│   └── about.py
├── templates/
│   ├── base.html            # Top navbar, Bootstrap 5, Open Sans
│   ├── home/
│   ├── warehouse/
│   ├── shipping/
│   ├── tsr_prep/
│   ├── maintenance/
│   └── about/
├── scripts/
│   └── scrape_gas_prices.py # Cron job: scrape AAA gas prices → MySQL
├── schemas/                 # Pydantic request/response models (one file per domain)
├── static/
│   └── assets/              # Images: MaxT1_conus.png, national_forecast.jpg
└── tests/
```

---

## Architecture

### App Factory (`main.py`)
Creates the FastAPI app, includes all routers with prefixes, and mounts the `static/` directory.

### Database (`database.py`)
Hardcoded connection — do not move credentials to env vars unless asked:

```python
user = "root"
password = "n1cenclean"
host = "172.17.15.228"
port = 3306
database = "warship"
# connection string: mysql+mysqlconnector://root:n1cenclean@172.17.15.228:3306/warship
```

The `connect_to_database()` function returns a SQLAlchemy `Engine`.

### Routing Pattern
- HTML pages use `Jinja2Templates.TemplateResponse()`
- JSON API endpoints declare a Pydantic `response_model=` on the decorator and return a model instance — never a raw dict
- Pydantic schemas live in `schemas/` (e.g. `schemas/health.py`), separate from SQLAlchemy models
- All routers use `APIRouter()` and are included in `main.py`

### Pages & Routes

| Page | Route | Notes |
|------|-------|-------|
| Home | `GET /` | Opens with weather images + gas prices card + quick access nav |
| Gas Prices | `GET /api/gas-prices` | JSON — latest national avg gas prices from `gas_prices` table (scraped from AAA via cron at 7:30 AM) |
| Gas Prices History | `GET /api/gas-prices/history` | JSON — full historical series from `gas_prices` (`id`, `fuel_type`, `price`, `scraped_at`) used by Home page multi-line trend chart (one line per fuel type). |
| Meeting Report | `GET /meeting-report` | Sub-page of Home; filter form (site, product_group, date) |
| Meeting Report Results | `GET /api/meeting-report/results` | HTMX partial — runs aggregated shipping query and returns group cards + report elements for selected filters. |
| Meeting Report All Site MTD | `GET /api/meeting-report/all-site-mtd` | HTMX partial — standalone All Site shipped weight/pallet table (AMJK, TXAS, AMIN, AMAZ) for selected `year_month` (`YYYY-MM`) month-to-date; independent of Truck Appointment Date filter. |
| Meeting Report Today Summary | `GET /api/meeting-report/today-summary` | HTMX partial — standalone selected-month target-day shipped weight/pallet table (AMJK, TXAS, AMIN, AMAZ). Uses selected `year_month` (`YYYY-MM`): current month = today, past month = month-end day. |
| Meeting Report Warehouse Pallet Movement MTD | `GET /api/meeting-report/warehouse-pallet-movement-mtd` | HTMX partial — standalone Warehouse pallet entry/exit + shipped card for AMJK/SW controlled by selected `year_month` (`YYYY-MM`) month-to-date, independent of Truck Appointment Date filter. |
| Briefing | `GET /briefing` | VIP Operations Briefing — printable snapshot of ops metrics |
| Weight by Year | `GET /api/analytics/weight-by-year` | JSON — monthly pick_weight per year series; params: `site` (default AMJK), `product_group` (default SW) |
| Freight Lbs by Year | `GET /api/analytics/freight-lbs-by-year-mei` | JSON — monthly lbs from `frt_cost_breakdown_mei`; param: `site` (default SW) |
| Unit Freight Cost John | `GET /api/analytics/unit-frt-cost-john` | JSON — all rows from `unit_frt_cost_john`: id, yyyy, mm, division, product, wt_lbs, freight |
| Freight Cost by Plant | `GET /api/analytics/freight-cost-by-plant` | JSON — annual YTD freight cost ($) by plant (BP, SW, CT, YA, Total) for 2019–2026; reads Excel workbook `AMJK Frt cost breakdown by plants-26.02.03.xlsx` |
| Warehouse | `GET /warehouse` | UDC hourly bar chart, UDC history line chart, ASH event heatmap — queries `udc_hourly_ash`, `udc_ash`, `event_ash` tables directly via SQLAlchemy |
| Shipping | `GET /shipping` | Filter bar (date range, site, product group) drives Carrier Cost Analysis card |
| Carrier Cost Analysis | `GET /api/carrier-cost-analysis` | JSON — calls `sp_carrier_cost_per_pound`; params: `date_from`, `date_to`, `site`, `product_group` (all optional); returns carrier_id, bl_count, total_weight, total_pallets, total_freight_cost, cost_per_pound. Card embedded at bottom of `/shipping` page with Plotly bubble chart + sortable table. |
| TSR Prep | `GET /tsr-prep` | Available-to-ship BL list + Google Map with nearest-neighbor lines and radius circles. Same-city customers are jittered so each gets a separate pin. |
| Pallet Entry/Exit | `GET /api/warehouse/pallet-entry-exit` | JSON — pallet entry (day+night in) and exit (1st+2nd+3rd out) from `daily_shift_averages`; params: `date_from`, `date_to` |
| Product Forecast | `GET /warehouse/product-forecast` | Interactive dashboard: per-product trend direction (INCREASE/DECREASE/STABLE), momentum, linear regression forecast, R², Chart.js line chart. Data from `sp_get_all_shipped_product`. |
| Product Forecast API | `GET /api/warehouse/product-forecast` | JSON — per-product forecast metrics; params: `site` (AMJK), `product_group` (SW), `start_date` (2010-01-01), `end_date` (2026-04-01), `min_months` (6). Returns months, trends, forecast list, summary counts. |
| Shipping Status CRUD | `GET /maintenance/shipping-status` | Maintenance data-entry page for table `shipping_status` with inline update/delete and create form. |
| Shipping Status API | `GET/POST/PUT/DELETE /maintenance/api/shipping-status...` | JSON CRUD endpoints for `shipping_status` (`id`, `Date`, `Customer`, `Con_Hou`, `Con_Rem`, `Con_PHO`, `Con_CHA`, `Total`, `Hou_ship`, `Rem_ship`, `Con`). |
| Freight ¢/lb Audit | `GET /maintenance/freight-audit` | Cross-checks ¢/lb calculations across all pages using 3 independent methods (Unit_Freight weighted avg, Freight_Amount all-in, SP). Shows per-carrier breakdown and sample BL verification. |
| Upload not in XFCMA | `GET /maintenance/not-in-xfcma` | Maintenance page for PDF upload with success/failure indication only. |
| Upload not in XFCMA API | `GET/POST/PUT/DELETE /maintenance/api/not-in-xfcma...` | JSON CRUD endpoints for `not_in_xfcma` (`id`, `report_datetime`, `product_code`, `manu_order`, `item`, `pallet`, `location`, `rolls`, `length`, `weight`, `grade`, `last_in_date`, `created_at_utc`, `source_file`). List supports optional filters: `product_code`, `date_from`, `date_to`. |
| Upload not in XFCMA PDF API | `POST /maintenance/api/not-in-xfcma/upload` | Multipart PDF upload endpoint. Parses QPQUPRFIL report rows and bulk inserts mapped records into `not_in_xfcma`; re-uploading the same filename replaces that file's prior rows. |
| Silos Status | `GET /maintenance/silos-status` | Page for daily Site Status CSV upload into `silo_status` (legacy alias: `GET /maintenance/site-status-upload`). |
| Upload Site Status CSV API | `POST /maintenance/api/site-status/upload` | Multipart CSV upload endpoint. Validates required headers, parses rows, auto-creates `silo_status` table if missing, bulk inserts rows, and rejects duplicate filenames with warning (no re-upload overwrite). |
| About | `GET /about` | |
| Health | `GET /health` | Returns `{"status": "ok", "service": "warship", "version": "0.1.0"}` |

### Software Architectural Page
The route reads a Markdown source file and renders it to HTML using **Pygments** for syntax highlighting. A **JavaScript-generated Bootstrap scrollspy TOC sidebar** is built from heading elements at page load. Required sections: Introduction, System Overview, Architectural Styles & Patterns, Technology Stack, Data Model, Folder Structure, API Endpoints, Deployment & Scaling, Security & Compliance, Future Roadmap.

---

## UI/UX Standards

This app targets a professional internal tool audience. Every page must feel polished.

### Design System
- **Primary color:** IBM Blue `#154e9a` — used for navbar, buttons, active states, links
- **Font:** Open Sans via Google Fonts — load in `base.html`
- **Framework:** Bootstrap 5 — use utility classes first, custom CSS only when Bootstrap cannot achieve the result
- **Icons:** Bootstrap Icons (`bi-*`) — consistent throughout, never mix icon libraries
- **Dashboard visual language:** Use the shared Greptile-inspired light shell (soft radial background accents, glassy white surfaces, rounded cards, and compact section bars) for newly refreshed pages.
- **Section headings:** Reuse a shared heading style for dashboard/page sections so titles keep the same font family, weight, size, and IBM Blue treatment across cards and subsections
- **Page and card headers:** Use the shared global classes in `static/css/custom.css` for page titles, default card headers, primary card headers, and filter cards; avoid inline header colors in templates

### Layout Rules
- All pages extend `base.html` — never inline a full HTML skeleton in a child template
- Page content sits inside a `container` or `container-fluid` with consistent vertical padding (`py-4`)
- Tables use `table table-striped table-hover table-sm` with a sticky `thead`
- Cards use `shadow-sm` for depth; avoid heavy borders
- Forms: labels above inputs, `form-floating` where it looks good, validation feedback always visible

### Interactivity
- Use **HTMX** for partial page updates (table refreshes, form submissions) — avoids full-page reloads
- Show a Bootstrap `spinner-border` during any async operation
- Use Bootstrap **Toast** (bottom-right) for success/error feedback — never use `alert()`
- Confirm destructive actions with a Bootstrap **modal**, not `confirm()`

### Responsiveness
- Mobile-first. Every layout must work at 375 px wide.
- Navbar collapses to hamburger on small screens and remains sticky at the top during scroll
- Tables that cannot reflow wrap in `table-responsive`

### Accessibility
- All `<img>` tags must have descriptive `alt` text
- All form inputs must have a `<label>` or `aria-label`
- Color alone must never convey meaning — pair color with an icon or text

---

## Deployment

### Current: Direct (no container)
- App runs directly via `uv run fastapi dev main.py --port 8088 --host 0.0.0.0` on the host machine
- Dokploy is **not currently used** — may be adopted in the future

### Dockerfile (future / optional)
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8088"]
```

### GitHub
- Default branch: `main`

---

## Coding Standards

- Every function and class must have a docstring or inline comments explaining the logic.
- Every API endpoint must have a `summary` and `description` in the decorator for Swagger docs.
- Use `APIRouter` in each router file; never define routes directly on the `app` object.

## Dependencies (current)

Managed via `pyproject.toml` / `uv.lock`:

| Package | Purpose |
|---------|---------|
| `fastapi[standard]` | Web framework + uvicorn + extras |
| `sqlalchemy` | ORM / database engine |
| `mysql-connector-python` | MySQL driver |
| `pygments` | Syntax highlighting for Software Architectural page |
| `markdown` | Markdown → HTML for Software Architectural page |
| `openpyxl` | Read Excel workbooks (`.xlsx`) for freight cost analytics |
| `beautifulsoup4` | HTML parsing for gas price scraper (`scripts/scrape_gas_prices.py`) |
| `pandas` | DataFrame aggregation for Meeting Report All Site MTD shipped weight/pallet summary |

---

## Keeping This Document Current

When completing any task, update CLAUDE.md if any of the following changed:
- A new route was added or removed → update the Pages & Routes table
- A new UI pattern or component was introduced → add it to UI/UX Standards
- A new dependency was added → update the Dependencies table
- A new sub-page or feature area was built → add it to Project Structure
