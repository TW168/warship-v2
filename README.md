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

---

## Production Work Order XLSX to JSON Mapping

Use this converter to process all `.xlsx` files in your current directory:

```bash
/home/tony/cfp/warship-v2/.venv/bin/python /home/tony/cfp/warship-v2/process_work_orders.py
```

### Sheet filtering

- Any sheet with a name that contains `Timeline` is skipped (case-insensitive).
- All other sheets are exported as individual JSON files named:
	- `<filename>_<sheetname>.json`

### JSON schema output

Each output `.json` file now contains one document with a single top-level `ticket` object:

- `ticket.line`
- `ticket.prod_date`
- `ticket.ewo`
- `ticket.shift`
- `ticket.crew`
- `ticket.prod_time`
- `ticket.operator`
- `ticket.charting[]`
- `ticket.downtime[]`
- `ticket.pallet[]`
- `ticket.material_usage.extruder[]`
- `ticket.material_usage.ext_b[]`
- `ticket.material_usage.ext_c[]`
- `ticket.material_usage.ext_d[]`
- `ticket.material_usage.comments`

### Excel cell mapping (based on `BE09_07102026_N.xlsx`)

#### Ticket header

| JSON key | Excel location |
|---|---|
| `ticket.line` | row 2, col 1 |
| `ticket.prod_date` | row 2, col 3 (ISO `YYYY-MM-DD`) |
| `ticket.ewo` | row 2, col 7 |
| `ticket.shift` | row 2, col 9 |
| `ticket.crew` | row 2, col 11 |
| `ticket.prod_time` | row 2, col 13 |
| `ticket.operator` | row 2, col 15 |

#### Charting

| JSON key | Excel location |
|---|---|
| `ticket.charting[0].chart` | row 7, col 1 |
| `ticket.charting[0].film_type` | row 9, col 1 |
| `ticket.charting[0].formula` | row 11, col 1 |
| `ticket.charting[0].pack_code` | row 13, col 1 |
| `ticket.charting[0].width` | row 15, col 1 |
| `ticket.charting[0].length` | row 17, col 1 |
| `ticket.charting[0].prod_weight_lbs` | row 19, col 1 |
| `ticket.charting[0].op_test_weight` | row 21, col 1 |
| `ticket.charting[0].qc_scrap_lbs` | row 23, col 1 |
| `ticket.charting[0].total_scrap` | row 25, col 1 |
| `ticket.charting[0].downtime` | row 27, col 1 |
| `ticket.charting[0].yield` | row 29, col 1 |
| `ticket.charting[0].weight_to_next` | row 31, col 1 |

#### Material usage

- Source blocks are in cols 13-16 under `EXTRUDER`, `EXT. B`, `EXT. C`, and `EXT. D`.
- Each block maps rows after its `Hopper / Silo / STD% / Input Lbs.` header until `TOTAL`.
- Maps as:
	- col 13 -> `ticket.material_usage.<section>[].hopper`
	- col 14 -> `ticket.material_usage.<section>[].silo`
	- col 15 -> `ticket.material_usage.<section>[].std`
	- col 16 -> `ticket.material_usage.<section>[].input_lbs`

#### Downtime

- Finds header row where col 1=`Code` and col 2=`Time`.
- Reads rows below until `TOTAL` or blank-run stop.
- Maps as:
	- col 1 -> `ticket.downtime[].code`
	- col 2 -> `ticket.downtime[].time`

#### Pallets

- Source rows start at row 7 using cols 4-11.
- Rows are included only when barcode is non-empty.
- Maps as:
	- col 7 -> `pallets[].barcode`
	- col 5 -> `pallets[].order_number`
	- col 8 -> `pallets[].weight_lbs`
	- col 10 -> `pallets[].qc_status`
	- col 9 -> `pallets[].roll`