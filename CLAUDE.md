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
│   ├── home.py              # GET / and GET /press
│   ├── warehouse.py
│   ├── shipping.py
│   ├── tsr_prep.py
│   ├── maintenance.py       # GET /maintenance/input, /maintenance/architectural
│   └── about.py
├── templates/
│   ├── base.html            # Top navbar, Bootstrap 5, Open Sans
│   ├── home/
│   ├── warehouse/
│   ├── shipping/
│   ├── tsr_prep/
│   ├── maintenance/
│   └── about/
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
| Home | `GET /` | Opens with `MaxT1_conus.png` and `national_forecast.jpg` side by side |
| Press | `GET /press` | Sub-page of Home |
| Warehouse | `GET /warehouse` | |
| Shipping | `GET /shipping` | |
| TSR Prep | `GET /tsr-prep` | |
| Maintenance Input | `GET /maintenance/input` | |
| Software Architectural | `GET /maintenance/architectural` | Markdown → HTML via Pygments; JS-generated Bootstrap scrollspy TOC sidebar |
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
- Navbar collapses to hamburger on small screens
- Tables that cannot reflow wrap in `table-responsive`

### Accessibility
- All `<img>` tags must have descriptive `alt` text
- All form inputs must have a `<label>` or `aria-label`
- Color alone must never convey meaning — pair color with an icon or text

---

## Deployment

### Dockerfile
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8088"]
```

### Dokploy
- Connect the GitHub repo in Dokploy → auto-deploys on push to `main`
- Set build type to **Dockerfile**
- Expose port **8088**
- No extra env vars needed (DB credentials are hardcoded)

### GitHub
- Default branch: `main`
- Dokploy webhook triggers on push; no CI workflow file required unless adding tests

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

---

## Keeping This Document Current

When completing any task, update CLAUDE.md if any of the following changed:
- A new route was added or removed → update the Pages & Routes table
- A new UI pattern or component was introduced → add it to UI/UX Standards
- A new dependency was added → update the Dependencies table
- A new sub-page or feature area was built → add it to Project Structure
