# Warship — Software Architecture

## Introduction

**Warship** (Warehouse and Shipping Management System) is an internal full-stack web application
designed to centralize warehouse inventory management, shipping logistics, and technical support
request (TSR) workflows into a single, cohesive platform.

This document describes the architectural decisions, technology choices, data model, and
deployment strategy for the Warship application. It is intended as a living reference for
developers and operators maintaining the system.

---

## System Overview

Warship follows a **server-rendered web application** model. The FastAPI backend handles all
routing: some routes return JSON (REST API), while others render Jinja2 HTML templates served
directly to the browser.

```
Browser ──HTTP──► FastAPI (Python)
                     │
                     ├── /             → Jinja2 Template
                     ├── /warehouse    → Jinja2 Template
                     ├── /shipping     → Jinja2 Template
                     ├── /tsr-prep     → Jinja2 Template
                     ├── /maintenance/* → Jinja2 Template
                     ├── /about        → Jinja2 Template
                     └── /health       → JSON Response
                             │
                        SQLAlchemy ORM
                             │
                        MySQL Database
```

HTMX is layered on top of the HTML pages to provide partial updates (e.g., form submissions,
table refreshes) without full page reloads, improving perceived performance.

---

## Architectural Styles & Patterns

### MVC-Like Separation

| Role | Implementation |
|------|---------------|
| Model | SQLAlchemy ORM models in `models/` |
| View | Jinja2 HTML templates in `templates/` |
| Controller | FastAPI route handlers in `routers/` |

### Router-per-Domain

Each business domain (warehouse, shipping, TSR prep, maintenance, home, about) lives in its own
`routers/` file. All routers are registered in `main.py`. This prevents a monolithic route file
and makes it easy to add new domains.

### Schema-First API Design

All JSON responses use Pydantic response models declared in `schemas/`. This ensures:

- Automatic OpenAPI/Swagger documentation with correct response shapes
- Type validation and serialization at the boundary
- Clear separation between SQLAlchemy ORM models and API contracts

### HTMX for Partial Rendering

Rather than building a separate SPA frontend, HTMX attributes on HTML elements trigger targeted
HTTP requests and swap only the affected part of the DOM. This keeps the stack simple (no
JavaScript build step) while delivering a dynamic user experience.

---

## Technology Stack

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Web framework | FastAPI | ≥ 0.133 | ASGI, auto OpenAPI, Pydantic v2 |
| ASGI server | Uvicorn | bundled | via `fastapi[standard]` |
| ORM | SQLAlchemy | ≥ 2.0 | Declarative ORM, async-ready |
| Database | MySQL | 8.x | Primary data store |
| DB driver | mysql-connector-python | ≥ 9.x | Pure-Python connector |
| Templating | Jinja2 | bundled | Server-side HTML rendering |
| Frontend framework | Bootstrap 5 | 5.3 | CDN, responsive utilities |
| Icons | Bootstrap Icons | 1.11 | CDN, consistent icon set |
| Interactivity | HTMX | 2.x | Partial page updates via CDN |
| Syntax highlighting | Pygments | ≥ 2.19 | Used on Architectural page |
| Markdown processing | markdown | ≥ 3.10 | Architectural page rendering |
| Package manager | uv | latest | Replaces pip + venv |
| Containerization | Docker | — | Multi-stage build |
| Deployment platform | Dokploy | — | Self-hosted PaaS, GitHub webhook |

---

## Data Model

> The database schema will be documented here as tables are defined in `models/`.

### Planned Entities

**WarehouseItem**

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment primary key |
| name | VARCHAR(255) | Item name |
| category | VARCHAR(100) | Item category |
| quantity | INT | Current stock level |
| location | VARCHAR(100) | Warehouse location (aisle, bin) |
| status | ENUM | `in_stock`, `low_stock`, `out_of_stock` |
| created_at | DATETIME | Record creation timestamp |
| updated_at | DATETIME | Last update timestamp |

**Shipment**

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment primary key |
| tracking_number | VARCHAR(100) | Carrier tracking number |
| destination | VARCHAR(255) | Delivery address |
| carrier | VARCHAR(100) | Shipping carrier name |
| ship_date | DATE | Date shipped |
| eta | DATE | Estimated arrival date |
| status | ENUM | `pending`, `in_transit`, `delivered`, `cancelled` |
| created_at | DATETIME | Record creation timestamp |

**TSR (Technical Support Request)**

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment primary key |
| title | VARCHAR(255) | Short description |
| description | TEXT | Detailed description |
| priority | ENUM | `low`, `medium`, `high`, `critical` |
| assigned_to | VARCHAR(100) | Responsible person or team |
| status | ENUM | `pending`, `in_progress`, `completed`, `cancelled` |
| created_at | DATETIME | Record creation timestamp |
| updated_at | DATETIME | Last update timestamp |

**MaintenanceRecord**

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment primary key |
| record_type | ENUM | `warehouse`, `shipping`, `equipment`, `software`, `other` |
| title | VARCHAR(255) | Short description |
| notes | TEXT | Detailed notes |
| status | ENUM | `open`, `in_progress`, `resolved`, `closed` |
| technician | VARCHAR(100) | Responsible technician |
| record_date | DATE | Date of the maintenance event |
| created_at | DATETIME | Record creation timestamp |

---

## Folder Structure

```
warship-v2/
├── main.py                  # FastAPI app factory — registers routers, mounts /static
├── database.py              # connect_to_database() → SQLAlchemy Engine
├── pyproject.toml           # uv project metadata and dependencies
├── uv.lock                  # Locked dependency tree for reproducible builds
├── Dockerfile               # Production container (python:3.12-slim + uv)
├── .gitignore
├── README.md
│
├── routers/                 # One APIRouter per domain
│   ├── __init__.py
│   ├── health.py            # GET /health
│   ├── home.py              # GET /  GET /meeting-report  GET /api/meeting-report/results  GET /press
│   ├── warehouse.py         # GET /warehouse
│   ├── shipping.py          # GET /shipping
│   ├── tsr_prep.py          # GET /tsr-prep
│   ├── maintenance.py       # GET /maintenance/input  GET /maintenance/architectural
│   └── about.py             # GET /about
│
├── schemas/                 # Pydantic response/request models (never raw dicts)
│   ├── __init__.py
│   └── health.py            # HealthResponse
│
├── models/                  # SQLAlchemy ORM models (to be added per domain)
│   └── __init__.py
│
├── templates/               # Jinja2 HTML templates
│   ├── base.html            # Navbar, Bootstrap 5, Open Sans, HTMX, Toast
│   ├── home/
│   │   ├── index.html
│   │   ├── meeting_report.html
│   │   └── press.html
│   ├── warehouse/index.html
│   ├── shipping/index.html
│   ├── tsr_prep/index.html
│   ├── maintenance/
│   │   ├── input.html
│   │   └── architectural.html
│   └── about/index.html
│
├── static/
│   ├── css/custom.css       # IBM Blue overrides, table headers, TOC styles
│   └── assets/              # MaxT1_conus.png, national_forecast.jpg
│
└── docs/
    └── architectural.md     # This document (source for /maintenance/architectural)
```

---

## API Endpoints

### System

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| GET | `/health` | JSON | Service health status |
| GET | `/docs` | HTML | Swagger UI |
| GET | `/redoc` | HTML | ReDoc API documentation |

### HTML Pages (Template Responses)

| Method | Path | Template | Description |
|--------|------|----------|-------------|
| GET | `/` | `home/index.html` | Home page with forecast images |
| GET | `/meeting-report` | `home/meeting_report.html` | Meeting report filter form (site, product_group, date) |
| GET | `/api/meeting-report/results` | `home/meeting_report_results.html` | HTMX partial — aggregated shipping query, returns group cards |
| GET | `/press` | `home/press.html` | Press releases sub-page |
| GET | `/warehouse` | `warehouse/index.html` | Warehouse inventory dashboard |
| GET | `/shipping` | `shipping/index.html` | Shipping management dashboard |
| GET | `/tsr-prep` | `tsr_prep/index.html` | TSR tracking dashboard |
| GET | `/maintenance/input` | `maintenance/input.html` | Data entry form |
| GET | `/maintenance/architectural` | `maintenance/architectural.html` | This document rendered as HTML |
| GET | `/about` | `about/index.html` | About page |

---

## Deployment & Scaling

### Local Development

```bash
uv sync                        # Install all dependencies into .venv
uv run fastapi dev main.py     # Hot-reload dev server at http://localhost:8000
```

### Docker Build

The Dockerfile uses `python:3.12-slim` and copies the `uv` binary from the official image for
fast, reproducible dependency installs:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
```

`uv sync --frozen` uses `uv.lock` to guarantee the exact same package versions in production
as in development.

### Dokploy Deployment

1. Push code to the `main` branch on GitHub.
2. Dokploy receives a webhook and rebuilds the Docker image.
3. The container is started and exposed on port **8000**.
4. No environment variables are required — database credentials are hardcoded.

### Scaling Considerations

- The app is stateless; multiple replicas can be run behind a load balancer.
- The MySQL database is the shared state; connection pooling is handled by SQLAlchemy.
- For heavier loads, replace the single MySQL host with a read replica setup.

---

## Security & Compliance

### Current Posture

| Area | Status | Notes |
|------|--------|-------|
| Database credentials | Hardcoded | Acceptable for internal deployment; do not expose publicly |
| HTTPS | Delegated | Handled at the Dokploy / reverse proxy layer (e.g., Traefik + Let's Encrypt) |
| Authentication | Not implemented | Planned for a future release |
| Input validation | Pydantic | All API request/response bodies validated via Pydantic models |
| SQL injection | ORM | SQLAlchemy parameterized queries prevent SQL injection |
| XSS | Jinja2 auto-escape | Jinja2 auto-escapes all template variables by default |
| CSRF | Not implemented | Required when form POST endpoints are added |

### Recommendations for Production

- Move database credentials to environment variables or a secrets manager.
- Enable HTTPS at the reverse proxy level (Traefik with Let's Encrypt is built into Dokploy).
- Add session-based or JWT authentication before exposing to non-trusted networks.
- Add CSRF tokens to all state-changing forms.

---

## Future Roadmap

| Feature | Priority | Notes |
|---------|----------|-------|
| User authentication | High | Login/logout, role-based access (admin, operator, viewer) |
| SQLAlchemy models | High | Define ORM models for all planned entities |
| CRUD API endpoints | High | POST/PUT/DELETE for warehouse items, shipments, TSRs |
| HTMX-powered tables | Medium | Live search and pagination without page reloads |
| Dashboard charts | Medium | Chart.js or ApexCharts for inventory and shipment trends |
| Email notifications | Medium | Alerts for low stock or shipment status changes |
| Export to CSV/Excel | Medium | Bulk export for warehouse and shipping data |
| Audit log | Low | Track all data changes with user + timestamp |
| Dark mode | Low | Toggle light/dark theme via CSS custom properties |
| Unit and integration tests | Ongoing | pytest coverage for all routes and business logic |
