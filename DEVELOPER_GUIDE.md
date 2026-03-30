# Warship Developer Guide

Welcome to the Warship codebase! This guide will help you understand the project structure, how to run the app, and how to safely make modifications.

---

## Table of Contents
- [Project Overview](#project-overview)
- [Folder Structure](#folder-structure)
- [How to Run the App](#how-to-run-the-app)
- [Routers: API & Page Endpoints](#routers-api--page-endpoints)
- [Schemas: Data Contracts](#schemas-data-contracts)
- [Templates: UI Layouts](#templates-ui-layouts)
- [Database Connection](#database-connection)
- [Adding or Modifying Features](#adding-or-modifying-features)
- [Testing](#testing)
- [Coding Standards](#coding-standards)
- [FAQ & Further Reading](#faq--further-reading)

---

## Project Overview

**Warship** is a Warehouse and Shipping Management System built with FastAPI, SQLAlchemy, MySQL, and Jinja2/Bootstrap 5. It provides:
- Professional, light-themed internal dashboards
- Modular API and HTML endpoints
- Data analytics and reporting for logistics operations

---

## Folder Structure

```
warship-v2/
├── main.py            # FastAPI app factory, mounts routers
├── database.py        # SQLAlchemy engine factory
├── routers/           # All API/page routers (one file per domain)
├── schemas/           # Pydantic models for request/response
├── templates/         # Jinja2 HTML templates (Bootstrap 5)
├── static/            # CSS, images, and assets
├── scripts/           # Data import/scraping scripts
├── tests/             # Test files (pytest)
├── pyproject.toml     # Dependency and project metadata
├── uv.lock            # Locked dependencies for reproducibility
├── README.md          # Quickstart and basic info
├── CLAUDE.md          # Living architecture and conventions doc
└── ...
```

---

## How to Run the App

1. **Install dependencies:**
   ```bash
   uv sync
   ```
2. **Run the development server:**
   ```bash
   uv run fastapi dev main.py --port 8088
   ```
   - App: http://localhost:8088
   - API docs: http://localhost:8088/docs
   - Health check: http://localhost:8088/health

---

## Routers: API & Page Endpoints

All routes are defined in the `routers/` folder. Each file defines an `APIRouter` for a specific domain or page. These are included in `main.py`.

| File              | Purpose/Domain         | Example Routes (HTTP method & path) |
|-------------------|-----------------------|-------------------------------------|
| health.py         | Health check          | GET /health                        |
| home.py           | Home, analytics, meeting report | GET /, GET /meeting-report, GET /api/gas-prices |
| warehouse.py      | Warehouse analytics   | GET /warehouse, GET /api/warehouse/udc-hourly |
| shipping.py       | Shipping dashboard    | GET /shipping, GET /api/carrier-cost-analysis |
| tsr_prep.py       | TSR Prep, Excel upload, mapping | GET /tsr-prep, POST /api/tsr-prep/upload |
| maintenance.py    | Maintenance tools, CRUD, audits | GET /maintenance/shipping-status, GET /maintenance/freight-audit |
| about.py          | About, architecture   | GET /about, GET /about/architectural |

- Each router uses `APIRouter()` and is imported in `main.py`.
- HTML pages use Jinja2 templates; JSON endpoints use Pydantic schemas for response models.

---

## Schemas: Data Contracts

- All request and response models are defined in `schemas/` (one file per domain).
- These are Pydantic models (v2) and are used for validation and OpenAPI docs.
- Example: `schemas/shipped_product.py` defines the response for shipped products endpoints.

---

## Templates: UI Layouts

- All HTML is rendered using Jinja2 templates in `templates/`.
- Each domain/page has its own subfolder (e.g., `templates/shipping/`, `templates/warehouse/`).
- All pages extend `base.html` (includes navbar, Bootstrap 5, Open Sans font).

---

## Database Connection

- The app uses a MySQL database at `172.17.15.228:3306`, database `warship`.
- Connection logic is in `database.py` using SQLAlchemy and `mysql-connector-python`.
- Credentials are hardcoded (see `database.py`).

---

## Adding or Modifying Features

1. **Add or update a router:**
   - Create or edit a file in `routers/`.
   - Define routes using `@router.get`, `@router.post`, etc.
   - Use Pydantic schemas for request/response models.
   - Register the router in `main.py` if new.
2. **Update schemas:**
   - Add or modify Pydantic models in `schemas/`.
3. **Edit templates:**
   - Update or add Jinja2 templates in the relevant `templates/` subfolder.
4. **Document your changes:**
   - Update `CLAUDE.md` and this guide if you add new routes, models, or UI patterns.

---

## Testing

- All tests are in the `tests/` folder and use `pytest`.
- Run all tests:
  ```bash
  uv run pytest
  ```
- Run a single test file:
  ```bash
  uv run pytest tests/test_health.py -v
  ```

---

## Coding Standards

- One router per domain/page, always use `APIRouter()`.
- All API endpoints must use Pydantic schemas for request/response.
- Every function/class should have a docstring or inline comment.
- UI: Professional, light theme only. Use Bootstrap 5, Open Sans, and IBM Blue (`#154e9a`).
- Use HTMX for partial page updates and Bootstrap Toasts for feedback.
- See `CLAUDE.md` for full UI/UX and architecture standards.

---

## FAQ & Further Reading

- **Architecture, UI/UX, and route catalog:** See `CLAUDE.md`
- **Quickstart and troubleshooting:** See `README.md`
- **Adding new endpoints or models:** See this guide and `CLAUDE.md`
- **Questions?**
  - Check the docstrings in each router and schema file
  - Review the OpenAPI docs at `/docs`

---

*Keep this guide up to date as you add new features or change the project structure!*
