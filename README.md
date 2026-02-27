# Warship

Warehouse and Shipping Management System built with FastAPI, Bootstrap 5, and MySQL.

---

## Requirements

- [Python 3.12+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- MySQL server running at `172.17.15.228:3306` with a `warship` database

---

## Getting Started

### 1. Install dependencies

```bash
uv sync
```

### 2. Run the development server

```bash
uv run fastapi dev main.py --port 8088
```

The app will be available at **http://localhost:8088**

API docs (Swagger UI): **http://localhost:8088/docs**

Health check: **http://localhost:8088/health**

---

## Run Tests

```bash
# All tests
uv run pytest

# Single test file
uv run pytest tests/test_health.py -v
```

---

## Install uv (if not installed)

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
## Run
uv run fastapi dev main.py --port 8088
uv run fastapi dev main.py --port 8088 --host 0.0.0.0

## Crontab -e get weather map 6AM daily
0 6 * * * wget -O /home/tony/cfp/warship-v2/static/assets/MaxT1_conus.png https://graphical.weather.gov/images/conus/Ma>
0 6 * * * wget -O /home/tony/cfp/warship-v2/static/assets/national_forecast.jpg https://www.wpc.ncep.noaa.gov/noaa/nati>