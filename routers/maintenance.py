"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
    GET /maintenance/shipping-status      — Shipping Status CRUD page
    GET /maintenance/api/shipping-status  — JSON list shipping_status rows
    POST /maintenance/api/shipping-status — JSON create shipping_status row
    PUT /maintenance/api/shipping-status/{id} — JSON update shipping_status row
    DELETE /maintenance/api/shipping-status/{id} — JSON delete shipping_status row
  GET /maintenance/frt-validation   — Freight ¢/lb by Product Code validation tool
  GET /maintenance/freight-audit    — Freight ¢/lb calculation audit page
  GET /api/maintenance/freight-audit — JSON audit data
  GET /maintenance/lmi              — LMI document analysis page
  POST /maintenance/lmi/analyze     — Stream AI bullet-point takeaways via Ollama
  GET /maintenance/truck-load-map   — Interactive truck trailer load planning tool
  GET /maintenance/not-in-xfcma     — Upload not in XFCMA page
  GET /maintenance/api/not-in-xfcma — JSON list not_in_xfcma rows
  POST /maintenance/api/not-in-xfcma — JSON create not_in_xfcma row
  PUT /maintenance/api/not-in-xfcma/{id} — JSON update not_in_xfcma row
  DELETE /maintenance/api/not-in-xfcma/{id} — JSON delete not_in_xfcma row
    GET /maintenance/silos-status           — Silos Status page
    GET /maintenance/site-status-upload     — Legacy alias for Silos Status page
    POST /maintenance/api/site-status/upload — Upload Site Status CSV and insert rows
"""

import csv
import io
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pdfplumber
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import text

from database import connect_to_database
from schemas.shipping_status import (
    ShippingStatusCreateRequest,
    ShippingStatusDeleteResponse,
    ShippingStatusRow,
    ShippingStatusUpdateRequest,
)
from schemas.not_in_xfcma import (
    NotInXfcmaCreateRequest,
    NotInXfcmaDeleteResponse,
    NotInXfcmaRow,
    NotInXfcmaUpdateRequest,
)
from utils.inas400_pdf_parser import _as400_date, _parse_pdf

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# Directory containing LMI source documents
_LMI_DIR = Path(__file__).parent.parent / "raw_data" / "lmi"

# Pre-computed LMI scores CSV
_LMI_SCORES_CSV = Path(__file__).parent.parent / "raw_data" / "lmi_scores.csv"

# Supported file extensions for LMI analysis
_SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".txt", ".csv"}

# Ollama config
_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODEL = "deepseek-r1:8b"

# Max characters of document text sent to model (keeps prompt within context window)
_MAX_TEXT_CHARS = 12_000
_XFCMA_LINE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)(?:\s+([A-Za-z0-9]{1,5}))?\s+(\d{2}/\d{2}/\d{2})$"
)

_SITE_STATUS_REQUIRED_HEADERS = {
    "Measurement Time",
    "Site",
    "Vessel Name",
    "Contents",
    "Vessel Type",
    "Distance Units",
    "Volume Units",
    "Weight Units",
    "Vessel Height",
    "Vessel Radius",
    "Vessel Length",
    "Vessel Width",
    "Hopper Height",
    "Outlet Radius",
    "Outlet Length",
    "Outlet Width",
    "Capacity Volume",
    "Sensor Type",
    "Sensor Address",
    "Measurement in Feet",
    "Measurement in Meters",
    "Product Density",
    "Density Units",
    "Product Volume",
    "Product Weight",
    "Product Height",
    "Headroom Volume",
    "Headroom Weight",
    "Headroom Height",
    "% Full",
    "Alarm Condition",
}


class AnalyzeRequest(BaseModel):
    """Request body for the LMI analyze endpoint."""
    filename: str


def _extract_text(path: Path) -> str:
    """Extract plain text from a supported file. Returns up to _MAX_TEXT_CHARS characters."""
    ext = path.suffix.lower()

    if ext == ".pdf":
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)[:_MAX_TEXT_CHARS]

    if ext in (".txt", ".csv"):
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_TEXT_CHARS]

    # DOCX / XLSX not yet wired — return a placeholder so the route still works
    return f"[File type {ext} extraction not yet implemented]"


def _build_prompt(filename: str, text: str) -> str:
    """Construct the Ollama prompt for bullet-point takeaways."""
    return (
        "Read the following document and provide 7-10 concise bullet point takeaways "
        "summarizing the most important findings, trends, and data points. "
        "Focus on logistics, supply chain, and economic metrics. "
        "Format as markdown bullet points using the • character as the prefix. "
        "Do not include any preamble, explanation, or closing remarks — "
        "start directly with the first bullet point.\n\n"
        f"Document: {filename}\n"
        "---\n"
        f"{text}\n"
        "---\n"
        "Bullet point takeaways:"
    )


async def _stream_ollama(prompt: str):
    """
    Async generator that streams text chunks from Ollama, stripping <think>…</think> blocks.
    Ollama streams newline-delimited JSON: {"response": "chunk", "done": false}
    """
    in_think = False
    think_buf = ""

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            _OLLAMA_URL,
            json={"model": _OLLAMA_MODEL, "prompt": prompt, "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line).get("response", "")
                except (json.JSONDecodeError, AttributeError):
                    continue

                # ── Strip <think>…</think> blocks ─────────────────────────
                # Feed chunk character-by-character into a state machine
                for char in chunk:
                    if in_think:
                        think_buf += char
                        if think_buf.endswith("</think>"):
                            in_think = False
                            think_buf = ""
                    else:
                        think_buf += char
                        if "<think>" in think_buf:
                            # Yield everything before the <think> tag, then enter think mode
                            pre = think_buf[: think_buf.index("<think>")]
                            if pre:
                                yield pre
                            think_buf = ""
                            in_think = True
                        elif len(think_buf) > 20:
                            # Safe to yield — no partial <think> tag forming
                            yield think_buf
                            think_buf = ""

                # Flush any remaining safe buffer
                if not in_think and think_buf and "<" not in think_buf:
                    yield think_buf
                    think_buf = ""



@router.get(
    "/frt-validation",
    response_class=HTMLResponse,
    summary="Freight ¢/lb by Product Code Validation",
    description=(
        "Interactive tool to validate the Freight ¢/lb by Product Code chart. "
        "Steps: raw API data table, per-product median check, top-50 weight filter, BL number lookup."
    ),
)
async def frt_validation(request: Request) -> HTMLResponse:
    """Render the freight ¢/lb validation tool page."""
    return templates.TemplateResponse(
        "maintenance/frt_validation.html",
        {"request": request, "active_page": "frt_validation"},
    )


_engine = connect_to_database()


def _row_to_shipping_status(row) -> ShippingStatusRow:
    """Map a SQLAlchemy row to a ShippingStatusRow model."""
    return ShippingStatusRow(
        id=int(row.id),
        date=row.date,
        customer=float(row.customer) if row.customer is not None else None,
        con_hou=float(row.con_hou) if row.con_hou is not None else None,
        con_rem=float(row.con_rem) if row.con_rem is not None else None,
        con_pho=float(row.con_pho) if row.con_pho is not None else None,
        con_cha=float(row.con_cha) if row.con_cha is not None else None,
        total=float(row.total) if row.total is not None else None,
        hou_ship=float(row.hou_ship) if row.hou_ship is not None else None,
        rem_ship=float(row.rem_ship) if row.rem_ship is not None else None,
        con=float(row.con) if row.con is not None else None,
    )


def _fetch_shipping_status_row(conn, row_id: int) -> ShippingStatusRow | None:
    """Fetch one shipping_status row by id."""
    row = conn.execute(
        text(
            """
            SELECT
                id,
                `Date` AS date,
                Customer AS customer,
                Con_Hou AS con_hou,
                Con_Rem AS con_rem,
                Con_PHO AS con_pho,
                Con_CHA AS con_cha,
                Total AS total,
                Hou_ship AS hou_ship,
                Rem_ship AS rem_ship,
                `Con` AS con
            FROM shipping_status
            WHERE id = :id
            """
        ),
        {"id": row_id},
    ).fetchone()
    if not row:
        return None
    return _row_to_shipping_status(row)


@router.get(
    "/shipping-status",
    response_class=HTMLResponse,
    summary="Shipping Status CRUD Page",
    description=(
        "Maintenance page to create, view, update, and delete records in the "
        "shipping_status table."
    ),
)
async def shipping_status_page(request: Request) -> HTMLResponse:
    """Render the shipping_status CRUD maintenance page."""
    return templates.TemplateResponse(
        "maintenance/shipping_status.html",
        {"request": request, "active_page": "shipping_status"},
    )


@router.get(
    "/api/shipping-status",
    response_model=list[ShippingStatusRow],
    summary="List shipping status rows",
    description=(
        "Returns shipping_status rows ordered by Date desc and id desc. "
        "Optional date filters can limit the result set."
    ),
)
async def shipping_status_list(
    date_from: Optional[str] = Query(None, description="Date >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Date <= (YYYY-MM-DD)"),
    limit: int = Query(200, ge=1, le=1000, description="Maximum rows to return"),
) -> list[ShippingStatusRow]:
    """Return shipping_status rows with optional date filters."""
    conditions = []
    params: dict = {"limit": limit}

    if date_from:
        try:
            start_date = datetime.fromisoformat(date_from.strip()).date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date_from: {exc}") from exc
        conditions.append("`Date` >= :date_from")
        params["date_from"] = start_date

    if date_to:
        try:
            end_date = datetime.fromisoformat(date_to.strip()).date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date_to: {exc}") from exc
        conditions.append("`Date` <= :date_to")
        params["date_to"] = end_date

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id,
                    `Date` AS date,
                    Customer AS customer,
                    Con_Hou AS con_hou,
                    Con_Rem AS con_rem,
                    Con_PHO AS con_pho,
                    Con_CHA AS con_cha,
                    Total AS total,
                    Hou_ship AS hou_ship,
                    Rem_ship AS rem_ship,
                    `Con` AS con
                FROM shipping_status
                {where_clause}
                ORDER BY `Date` DESC, id DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()

    return [_row_to_shipping_status(row) for row in rows]


@router.post(
    "/api/shipping-status",
    response_model=ShippingStatusRow,
    summary="Create shipping status row",
    description="Creates a new row in shipping_status.",
)
async def shipping_status_create(body: ShippingStatusCreateRequest) -> ShippingStatusRow:
    """Create one shipping_status row and return the inserted record."""
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO shipping_status (
                    `Date`, Customer, Con_Hou, Con_Rem, Con_PHO, Con_CHA,
                    Total, Hou_ship, Rem_ship, `Con`
                ) VALUES (
                    :date, :customer, :con_hou, :con_rem, :con_pho, :con_cha,
                    :total, :hou_ship, :rem_ship, :con
                )
                """
            ),
            {
                "date": body.date,
                "customer": body.customer,
                "con_hou": body.con_hou,
                "con_rem": body.con_rem,
                "con_pho": body.con_pho,
                "con_cha": body.con_cha,
                "total": body.total,
                "hou_ship": body.hou_ship,
                "rem_ship": body.rem_ship,
                "con": body.con,
            },
        )

        new_id = int(result.lastrowid) if result.lastrowid is not None else None
        if new_id is None:
            new_id = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())

        created = _fetch_shipping_status_row(conn, new_id)

    if not created:
        raise HTTPException(status_code=500, detail="Created row could not be retrieved")
    return created


@router.put(
    "/api/shipping-status/{row_id}",
    response_model=ShippingStatusRow,
    summary="Update shipping status row",
    description="Updates an existing shipping_status row by id.",
)
async def shipping_status_update(
    row_id: int,
    body: ShippingStatusUpdateRequest,
) -> ShippingStatusRow:
    """Update one shipping_status row and return the updated record."""
    with _engine.begin() as conn:
        exists = conn.execute(
            text("SELECT id FROM shipping_status WHERE id = :id"),
            {"id": row_id},
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Row not found: {row_id}")

        conn.execute(
            text(
                """
                UPDATE shipping_status
                SET
                    `Date` = :date,
                    Customer = :customer,
                    Con_Hou = :con_hou,
                    Con_Rem = :con_rem,
                    Con_PHO = :con_pho,
                    Con_CHA = :con_cha,
                    Total = :total,
                    Hou_ship = :hou_ship,
                    Rem_ship = :rem_ship,
                    `Con` = :con
                WHERE id = :id
                """
            ),
            {
                "id": row_id,
                "date": body.date,
                "customer": body.customer,
                "con_hou": body.con_hou,
                "con_rem": body.con_rem,
                "con_pho": body.con_pho,
                "con_cha": body.con_cha,
                "total": body.total,
                "hou_ship": body.hou_ship,
                "rem_ship": body.rem_ship,
                "con": body.con,
            },
        )

        updated = _fetch_shipping_status_row(conn, row_id)

    if not updated:
        raise HTTPException(status_code=500, detail="Updated row could not be retrieved")
    return updated


@router.delete(
    "/api/shipping-status/{row_id}",
    response_model=ShippingStatusDeleteResponse,
    summary="Delete shipping status row",
    description="Deletes one row from shipping_status by id.",
)
async def shipping_status_delete(row_id: int) -> ShippingStatusDeleteResponse:
    """Delete one shipping_status row by id."""
    with _engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM shipping_status WHERE id = :id"),
            {"id": row_id},
        )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Row not found: {row_id}")

    return ShippingStatusDeleteResponse(deleted_id=row_id, message="Row deleted")


@router.get(
    "/freight-audit",
    response_class=HTMLResponse,
    summary="Freight ¢/lb Calculation Audit",
    description=(
        "Audit page that cross-checks freight cost-per-pound calculations across "
        "all pages (Meeting Report, Carrier Cost SP, Briefing) using multiple "
        "independent formulas to verify correctness."
    ),
)
async def freight_audit(request: Request) -> HTMLResponse:
    """Render the freight calculation audit page."""
    return templates.TemplateResponse(
        "maintenance/freight_audit.html",
        {"request": request, "active_page": "freight_audit"},
    )


@router.get(
    "/api/freight-audit",
    summary="Freight ¢/lb audit data",
    description=(
        "Runs multiple independent queries against ipg_ez to cross-verify freight "
        "cost-per-pound calculations. Returns raw intermediate values so the UI "
        "can display each formula step-by-step."
    ),
)
async def freight_audit_api(
    site: Optional[str] = Query(None, description="Site code, e.g. AMJK"),
    product_group: Optional[str] = Query(None, description="Product group, e.g. SW"),
    date_from: Optional[str] = Query(None, description="Truck_Appointment_Date >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Truck_Appointment_Date <= (YYYY-MM-DD)"),
) -> JSONResponse:
    """Run audit queries and return comparison data.

    Uses the same NOT EXISTS deduplication as the SP to ensure apples-to-apples
    comparison across all methods.
    """
    # Build dynamic WHERE clause (matches SP logic exactly)
    conditions = [
        "s.Truck_Appointment_Date IS NOT NULL",
        "s.Product_Code NOT IN ('INSERT-C', 'INSERT-3')",
    ]
    params: dict = {}
    if site:
        conditions.append("s.Site = :site")
        params["site"] = site
    if product_group:
        conditions.append("s.Product_Group = :product_group")
        params["product_group"] = product_group
    if date_from:
        conditions.append("s.Truck_Appointment_Date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("s.Truck_Appointment_Date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions)

    # NOT EXISTS deduplication — same as SP, keeps only latest snapshot per BL
    dedup = """
        AND NOT EXISTS (
            SELECT 1 FROM ipg_ez n
            WHERE n.BL_Number = s.BL_Number
              AND (n.snap_ts > s.snap_ts
                   OR (n.snap_ts = s.snap_ts AND n.file_name > s.file_name))
        )
    """

    try:
        with _engine.connect() as conn:
            # ── Method A: Direct SQL with dedup (same logic as SP) ────────
            row_a = conn.execute(text(f"""
                SELECT
                    SUM(s.Unit_Freight * s.Pick_Weight) AS uf_x_pw,
                    SUM(s.Pick_Weight)                  AS total_weight,
                    SUM(s.Freight_Amount)               AS total_freight_amt,
                    COUNT(*)                            AS row_count,
                    COUNT(DISTINCT s.BL_Number)         AS bl_count
                FROM ipg_ez s
                WHERE {where}
                {dedup}
            """), params).fetchone()

            uf_x_pw        = float(row_a.uf_x_pw or 0)
            total_weight   = float(row_a.total_weight or 0)
            total_frt_amt  = float(row_a.total_freight_amt or 0)
            row_count      = int(row_a.row_count or 0)
            bl_count       = int(row_a.bl_count or 0)

            # Method A: weighted avg ¢/lb using Unit_Freight (the rate)
            method_a = round(uf_x_pw / total_weight, 4) if total_weight else 0
            # Method B: all-in ¢/lb using Freight_Amount (actual $ on BL)
            method_b = round((total_frt_amt / total_weight) * 100, 4) if total_weight else 0

            # ── Method C: Call the stored procedure ───────────────────────
            raw = conn.connection.driver_connection
            cursor = raw.cursor(dictionary=True)
            cursor.callproc(
                "sp_carrier_cost_per_pound",
                [date_from, date_to, site or None, product_group or None],
            )
            sp_rows = []
            sp_wtd_sum = 0.0
            sp_total_wt = 0
            sp_total_frt = 0.0
            for result_set in cursor.stored_results():
                for r in result_set.fetchall():
                    cpp = float(r["cost_per_pound"]) if r["cost_per_pound"] else 0
                    wt = int(r["total_weight"]) if r["total_weight"] else 0
                    frt = float(r["total_freight_cost"] or 0)
                    sp_rows.append({
                        "carrier_id": r["Carrier_ID"],
                        "total_weight": wt,
                        "total_freight_cost": frt,
                        "cost_per_pound": cpp,
                    })
                    sp_wtd_sum += cpp * wt
                    sp_total_wt += wt
                    sp_total_frt += frt
            cursor.close()

            method_c = round(sp_wtd_sum / sp_total_wt, 4) if sp_total_wt else 0

            # ── Sample BLs: compare Unit_Freight rate vs Freight_Amount ──
            samples = conn.execute(text(f"""
                SELECT
                    s.BL_Number,
                    s.Unit_Freight,
                    s.Pick_Weight,
                    s.Freight_Amount,
                    ROUND(s.Unit_Freight / 100.0 * s.Pick_Weight, 2) AS computed_freight
                FROM ipg_ez s
                WHERE {where}
                  {dedup}
                  AND s.Unit_Freight > 0
                  AND s.Pick_Weight > 0
                  AND s.Freight_Amount > 0
                ORDER BY RAND()
                LIMIT 15
            """), params).fetchall()

            sample_rows = []
            for s in samples:
                uf = float(s.Unit_Freight)
                pw = float(s.Pick_Weight)
                fa = float(s.Freight_Amount)
                computed = round(uf / 100.0 * pw, 2)
                diff = round(fa - computed, 2)
                sample_rows.append({
                    "bl": s.BL_Number,
                    "unit_freight": round(uf, 4),
                    "pick_weight": round(pw, 0),
                    "freight_amount": round(fa, 2),
                    "computed_freight": computed,
                    "diff": diff,
                })

    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return JSONResponse(content={
        "filters": {
            "site": site, "product_group": product_group,
            "date_from": date_from, "date_to": date_to,
        },
        "summary": {
            "row_count": row_count,
            "bl_count": bl_count,
            "total_weight": round(total_weight, 0),
            "total_freight_amt": round(total_frt_amt, 2),
            "uf_x_pw": round(uf_x_pw, 2),
        },
        "methods": {
            "a": {
                "label": "SUM(Unit_Freight × Pick_Weight) / SUM(Pick_Weight)",
                "description": "Weighted avg of the per-pound RATE from the Excel report",
                "unit": "¢/lb",
                "value": method_a,
                "source": "Direct SQL on ipg_ez with dedup",
            },
            "b": {
                "label": "SUM(Freight_Amount) / SUM(Pick_Weight) × 100",
                "description": "All-in cost per pound using actual BL dollar amounts (includes surcharges, fuel, etc.)",
                "unit": "¢/lb",
                "value": method_b,
                "source": "Freight_Amount column ($ on BL)",
            },
            "c": {
                "label": "SP sp_carrier_cost_per_pound → weighted avg",
                "description": "Stored procedure per-carrier ¢/lb, then weighted by carrier weight",
                "unit": "¢/lb",
                "value": method_c,
                "source": "Stored procedure (uses Unit_Freight + dedup)",
            },
        },
        "sp_summary": {
            "total_weight": sp_total_wt,
            "total_freight": round(sp_total_frt, 2),
        },
        "sp_carriers": sp_rows[:10],
        "samples": sample_rows,
    })


@router.get(
    "/lmi",
    response_class=HTMLResponse,
    summary="LMI Document Analysis",
    description=(
        "Lists all documents in raw_data/lmi/ and provides AI-powered bullet-point "
        "takeaways for each via local Ollama (deepseek-r1:8b)."
    ),
)
async def lmi_page(request: Request) -> HTMLResponse:
    """Render the LMI document analysis page."""
    files = sorted(
        [f.name for f in _LMI_DIR.glob("*") if f.suffix.lower() in _SUPPORTED_EXTS]
    )
    # Pre-select current month's file; fall back to the last (most recent) file
    month_str = datetime.now().strftime("%B %Y")  # e.g. "March 2026"
    default_file = next((f for f in files if month_str in f), files[-1] if files else None)

    # Load historical LMI scores for the line chart
    lmi_scores: list[dict] = []
    if _LMI_SCORES_CSV.exists():
        with _LMI_SCORES_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lmi_scores.append({"date": row["date"], "lmi_score": float(row["lmi_score"])})

    return templates.TemplateResponse(
        "maintenance/lmi.html",
        {
            "request": request,
            "active_page": "lmi",
            "files": files,
            "default_file": default_file,
            "lmi_scores": lmi_scores,
        },
    )


@router.post(
    "/lmi/analyze",
    summary="Analyze an LMI document with Ollama",
    description=(
        "Reads the specified file from raw_data/lmi/, extracts its text, "
        "and streams bullet-point takeaways from local Ollama deepseek-r1:8b. "
        "<think> blocks are stripped before streaming to the client."
    ),
)
async def lmi_analyze(body: AnalyzeRequest) -> StreamingResponse:
    """Stream AI-generated bullet-point takeaways for the requested LMI document."""
    # Validate filename — no path traversal
    filename = Path(body.filename).name
    path = _LMI_DIR / filename
    if not path.exists() or path.suffix.lower() not in _SUPPORTED_EXTS:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    text = _extract_text(path)
    prompt = _build_prompt(filename, text)

    return StreamingResponse(
        _stream_ollama(prompt),
        media_type="text/plain; charset=utf-8",
    )


@router.get(
    "/lmi/briefing-analysis",
    summary="Cross-month LMI analysis for Briefing page",
    description=(
        "Reads all LMI text files, builds a 15-month timeline, and streams "
        "a structured 5-question analysis from deepseek-r1:8b via Ollama."
    ),
)
async def lmi_briefing_analysis() -> StreamingResponse:
    """Stream a full cross-month LMI market analysis for the Operations Briefing page."""
    import re as _re

    _MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    _SCORE_RE = _re.compile(r'LMI[®\s]{0,5}at\s+([\d]+\.[\d]+)', _re.IGNORECASE)

    records = []
    for f in sorted(_LMI_DIR.glob("*.txt")):
        stem = f.stem.lower()
        m = _re.match(r"lmi_([a-z]+)_?(\d{4})", stem)
        if not m:
            continue
        mo = _MONTH_MAP.get(m.group(1)[:3])
        if not mo:
            continue
        month_id = f"{m.group(2)}-{mo:02d}"
        text = f.read_text(encoding="utf-8", errors="ignore")
        score_m = _SCORE_RE.search(text)
        score = score_m.group(1) if score_m else "?"
        paras = [l.strip() for l in text.splitlines() if len(l.strip()) > 100]
        body = " | ".join(paras[:5])[:1200]
        records.append((month_id, score, body))

    records.sort(key=lambda x: x[0])
    timeline = "\n".join(
        f"{mid} (LMI {score}): {body}" for mid, score, body in records
    )

    prompt = (
        "You are a blunt, senior logistics analyst. Read the following 15 months of LMI source data.\n"
        "Every claim you make MUST cite the exact month and score from the text below.\n\n"
        "--- SOURCE DATA START ---\n"
        f"{timeline}\n"
        "--- SOURCE DATA END ---\n\n"
        "Answer these 5 questions. Be direct. Use month-year and scores as evidence. No fluff.\n\n"
        "**Q1. TREND ARC** (2-3 sentences): Summarize Jan 2025 → Mar 2026 as one coherent story using actual scores.\n\n"
        "**Q2. THREE TURNING POINTS**: For each, give month, score, score change, and the specific cause from the source text.\n\n"
        "**Q3. MOST UNUSUAL READING**: Which single sub-metric value in any month is most abnormal? "
        "Quote the exact source text phrase that explains why.\n\n"
        "**Q4. MAR 2026 SIGNAL**: LMI 65.7, Transportation Prices 89.4. Based on the source text explanation "
        "of WHY (Strait of Hormuz / oil supply), what specifically should freight buyers expect in Q2 2026?\n\n"
        "**Q5. AMJK ACTION**: For a plastic film shipper in Houston with heavy outbound truck loads, "
        "what is the ONE most important action right now? Base it only on what the source text says."
    )

    return StreamingResponse(
        _stream_ollama(prompt),
        media_type="text/plain; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Truck Load Map
# ---------------------------------------------------------------------------

@router.get(
    "/truck-load-map",
    response_class=HTMLResponse,
    summary="Truck Load Map",
    description="Interactive truck trailer load planning tool — pallet placement with product catalogue from DB.",
)
async def truck_load_map(request: Request) -> HTMLResponse:
    """Render the Truck Load Map planning page.

    Queries warship.Product_desc_size to populate the product dropdown in the
    Add Pallet sidebar card.  If the DB is unreachable the page still loads with
    an empty dropdown (graceful degradation).
    """
    products: list[dict] = []
    try:
        with _engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, product_description, product, "
                "pallet_length, pallet_width, pallet_height, product_groww_weight "
                "FROM warship.Product_desc_size ORDER BY product_description"
            )).fetchall()
            products = [
                {
                    "id": r.id,
                    "product_description": r.product_description,
                    "product": r.product,
                    "pallet_length": float(r.pallet_length),
                    "pallet_width": float(r.pallet_width),
                    "pallet_height": float(r.pallet_height),
                    "product_groww_weight": float(r.product_groww_weight),
                }
                for r in rows
            ]
    except Exception:
        # DB unavailable — page still loads, dropdown will be empty
        pass

    return templates.TemplateResponse(
        "maintenance/truck_load_map.html",
        {"request": request, "active_page": "truck_load_map", "products": products},
    )


# ---------------------------------------------------------------------------
# Site Status CSV Upload
# ---------------------------------------------------------------------------

def _clean_csv_text(value: str | None) -> str:
    """Trim whitespace and remove wrapping single quotes from CSV text fields."""
    if value is None:
        return ""
    cleaned = value.strip()
    if cleaned.startswith("'") and cleaned.endswith("'") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _parse_float_or_none(value: str | None) -> float | None:
    """Safely parse a CSV numeric field into float or None when blank/invalid."""
    raw = _clean_csv_text(value)
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _ensure_silo_status_table() -> None:
    """Create silo_status table if it does not already exist."""
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS silo_status (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    measurement_time DATETIME NOT NULL,
                    site VARCHAR(100) NULL,
                    vessel_name VARCHAR(100) NULL,
                    contents VARCHAR(100) NULL,
                    vessel_type VARCHAR(100) NULL,
                    distance_units VARCHAR(50) NULL,
                    volume_units VARCHAR(50) NULL,
                    weight_units VARCHAR(50) NULL,
                    vessel_height DECIMAL(18,4) NULL,
                    vessel_radius DECIMAL(18,4) NULL,
                    vessel_length DECIMAL(18,4) NULL,
                    vessel_width DECIMAL(18,4) NULL,
                    hopper_height DECIMAL(18,4) NULL,
                    outlet_radius DECIMAL(18,4) NULL,
                    outlet_length DECIMAL(18,4) NULL,
                    outlet_width DECIMAL(18,4) NULL,
                    capacity_volume DECIMAL(18,4) NULL,
                    sensor_type VARCHAR(150) NULL,
                    sensor_address VARCHAR(50) NULL,
                    measurement_in_feet DECIMAL(18,4) NULL,
                    measurement_in_meters DECIMAL(18,4) NULL,
                    product_density DECIMAL(18,4) NULL,
                    density_units VARCHAR(50) NULL,
                    product_volume DECIMAL(18,4) NULL,
                    product_weight DECIMAL(18,4) NULL,
                    product_height DECIMAL(18,4) NULL,
                    headroom_volume DECIMAL(18,4) NULL,
                    headroom_weight DECIMAL(18,4) NULL,
                    headroom_height DECIMAL(18,4) NULL,
                    percent_full DECIMAL(9,4) NULL,
                    alarm_condition VARCHAR(120) NULL,
                    snapshot_date DATE NOT NULL,
                    source_file VARCHAR(255) NOT NULL,
                    uploaded_at_utc DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                    KEY ix_silo_status_snapshot_date (snapshot_date),
                    KEY ix_silo_status_vessel_name (vessel_name),
                    KEY ix_silo_status_source_file (source_file)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


@router.get(
    "/silos-status",
    response_class=HTMLResponse,
    summary="Silos Status Page",
    description=(
        "Silos Status page for daily Site Status CSV upload into the "
        "silo_status table."
    ),
)
@router.get(
    "/site-status-upload",
    response_class=HTMLResponse,
    summary="Silos Status Page (Legacy URL)",
    description=(
        "Legacy URL for the Silos Status page used to upload daily "
        "Site Status CSV files into the "
        "silo_status table."
    ),
)
async def site_status_upload_page(request: Request) -> HTMLResponse:
    """Render the Silos Status page."""
    return templates.TemplateResponse(
        "maintenance/site_status_upload.html",
        {"request": request, "active_page": "silos_status"},
    )


@router.post(
    "/api/site-status/upload",
    summary="Upload Site Status CSV",
    description=(
        "Upload one Site Status CSV file, parse rows, and insert records into "
        "silo_status. Duplicate filenames are rejected with a warning and "
        "not inserted again."
    ),
)
async def site_status_upload_csv(file: UploadFile = File(...)) -> JSONResponse:
    """Parse uploaded Site Status CSV and insert rows into silo_status."""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV encoding: {exc}") from exc

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is missing")

    missing_headers = sorted(_SITE_STATUS_REQUIRED_HEADERS - set(reader.fieldnames))
    if missing_headers:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required CSV headers: {', '.join(missing_headers)}",
        )

    rows_to_insert: list[dict] = []
    parsed_row_count = 0

    for csv_row in reader:
        parsed_row_count += 1
        measurement_time_raw = _clean_csv_text(csv_row.get("Measurement Time"))
        if not measurement_time_raw:
            continue

        try:
            measurement_time = datetime.strptime(measurement_time_raw, "%m/%d/%Y %I:%M:%S %p")
        except ValueError:
            continue

        rows_to_insert.append(
            {
                "measurement_time": measurement_time,
                "site": _clean_csv_text(csv_row.get("Site")),
                "vessel_name": _clean_csv_text(csv_row.get("Vessel Name")),
                "contents": _clean_csv_text(csv_row.get("Contents")),
                "vessel_type": _clean_csv_text(csv_row.get("Vessel Type")),
                "distance_units": _clean_csv_text(csv_row.get("Distance Units")),
                "volume_units": _clean_csv_text(csv_row.get("Volume Units")),
                "weight_units": _clean_csv_text(csv_row.get("Weight Units")),
                "vessel_height": _parse_float_or_none(csv_row.get("Vessel Height")),
                "vessel_radius": _parse_float_or_none(csv_row.get("Vessel Radius")),
                "vessel_length": _parse_float_or_none(csv_row.get("Vessel Length")),
                "vessel_width": _parse_float_or_none(csv_row.get("Vessel Width")),
                "hopper_height": _parse_float_or_none(csv_row.get("Hopper Height")),
                "outlet_radius": _parse_float_or_none(csv_row.get("Outlet Radius")),
                "outlet_length": _parse_float_or_none(csv_row.get("Outlet Length")),
                "outlet_width": _parse_float_or_none(csv_row.get("Outlet Width")),
                "capacity_volume": _parse_float_or_none(csv_row.get("Capacity Volume")),
                "sensor_type": _clean_csv_text(csv_row.get("Sensor Type")),
                "sensor_address": _clean_csv_text(csv_row.get("Sensor Address")),
                "measurement_in_feet": _parse_float_or_none(csv_row.get("Measurement in Feet")),
                "measurement_in_meters": _parse_float_or_none(csv_row.get("Measurement in Meters")),
                "product_density": _parse_float_or_none(csv_row.get("Product Density")),
                "density_units": _clean_csv_text(csv_row.get("Density Units")),
                "product_volume": _parse_float_or_none(csv_row.get("Product Volume")),
                "product_weight": _parse_float_or_none(csv_row.get("Product Weight")),
                "product_height": _parse_float_or_none(csv_row.get("Product Height")),
                "headroom_volume": _parse_float_or_none(csv_row.get("Headroom Volume")),
                "headroom_weight": _parse_float_or_none(csv_row.get("Headroom Weight")),
                "headroom_height": _parse_float_or_none(csv_row.get("Headroom Height")),
                "percent_full": _parse_float_or_none(csv_row.get("% Full")),
                "alarm_condition": _clean_csv_text(csv_row.get("Alarm Condition")),
                "snapshot_date": measurement_time.date(),
                "source_file": filename,
            }
        )

    if not rows_to_insert:
        raise HTTPException(
            status_code=400,
            detail="No valid rows found. Confirm Measurement Time format is MM/DD/YYYY HH:MM:SS AM/PM.",
        )

    _ensure_silo_status_table()

    with _engine.begin() as conn:
        existing = conn.execute(
            text("SELECT COUNT(*) FROM silo_status WHERE source_file = :source_file"),
            {"source_file": filename},
        ).scalar()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"File '{filename}' has already been uploaded. Each filename can only be uploaded once.",
            )

        result = conn.execute(
            text(
                """
                INSERT INTO silo_status (
                    measurement_time, site, vessel_name, contents, vessel_type,
                    distance_units, volume_units, weight_units,
                    vessel_height, vessel_radius, vessel_length, vessel_width,
                    hopper_height, outlet_radius, outlet_length, outlet_width,
                    capacity_volume, sensor_type, sensor_address,
                    measurement_in_feet, measurement_in_meters, product_density,
                    density_units, product_volume, product_weight, product_height,
                    headroom_volume, headroom_weight, headroom_height,
                    percent_full, alarm_condition, snapshot_date, source_file
                ) VALUES (
                    :measurement_time, :site, :vessel_name, :contents, :vessel_type,
                    :distance_units, :volume_units, :weight_units,
                    :vessel_height, :vessel_radius, :vessel_length, :vessel_width,
                    :hopper_height, :outlet_radius, :outlet_length, :outlet_width,
                    :capacity_volume, :sensor_type, :sensor_address,
                    :measurement_in_feet, :measurement_in_meters, :product_density,
                    :density_units, :product_volume, :product_weight, :product_height,
                    :headroom_volume, :headroom_weight, :headroom_height,
                    :percent_full, :alarm_condition, :snapshot_date, :source_file
                )
                """
            ),
            rows_to_insert,
        )
        inserted_count = int(result.rowcount or 0)

    # Run ETL to populate star-schema tables
    etl_result = _run_silo_etl(rows_to_insert[0]["snapshot_date"])

    return JSONResponse(
        content={
            "message": "Site Status CSV uploaded successfully",
            "source_file": filename,
            "csv_rows": parsed_row_count,
            "inserted": inserted_count,
            "snapshot_date": rows_to_insert[0]["snapshot_date"].isoformat(),
            "etl_vessels": etl_result.get("vessels_resolved", 0),
            "etl_facts": etl_result.get("fact_rows_inserted", 0),
        }
    )


# ---------------------------------------------------------------------------
# Silos ETL — populate star-schema from silo_status raw rows
# ---------------------------------------------------------------------------

def _run_silo_etl(snapshot_date) -> dict:
    """ETL pipeline for one snapshot_date.

    Reads raw rows from silo_status, upserts dimension tables
    (silo_dim_vessel, silo_dim_contents, silo_dim_alarm), loads
    fact_silo_status, then refreshes all five aggregate tables.

    Returns a dict with row counts for each step.
    """
    with _engine.begin() as conn:
        # ── 1. Resolve silo_dim_vessel ──────────────────────────────────────
        vessels = conn.execute(
            text(
                """
                SELECT DISTINCT vessel_name, site, vessel_type, distance_units,
                    volume_units, weight_units, vessel_height, vessel_radius,
                    vessel_length, vessel_width, hopper_height, outlet_radius,
                    outlet_length, outlet_width, capacity_volume,
                    sensor_type, sensor_address
                FROM silo_status
                WHERE snapshot_date = :sd AND vessel_name IS NOT NULL
                  AND vessel_name <> ''
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        vessel_map: dict[str, int] = {}
        for v in vessels:
            row = conn.execute(
                text("SELECT vessel_key FROM silo_dim_vessel WHERE vessel_name = :n AND is_current = 1"),
                {"n": v["vessel_name"]},
            ).fetchone()
            if row:
                vessel_map[v["vessel_name"]] = int(row[0])
            else:
                r = conn.execute(
                    text(
                        """
                        INSERT INTO silo_dim_vessel (
                            vessel_name, site, vessel_type, distance_units, volume_units,
                            weight_units, vessel_height, vessel_radius, vessel_length,
                            vessel_width, hopper_height, outlet_radius, outlet_length,
                            outlet_width, capacity_volume, sensor_type, sensor_address,
                            effective_from
                        ) VALUES (
                            :vessel_name, :site, :vessel_type, :distance_units, :volume_units,
                            :weight_units, :vessel_height, :vessel_radius, :vessel_length,
                            :vessel_width, :hopper_height, :outlet_radius, :outlet_length,
                            :outlet_width, :capacity_volume, :sensor_type, :sensor_address,
                            :effective_from
                        )
                        """
                    ),
                    {**dict(v), "effective_from": snapshot_date},
                )
                vessel_map[v["vessel_name"]] = int(r.lastrowid)

        # ── 2. Resolve silo_dim_contents ────────────────────────────────────
        contents_rows = conn.execute(
            text(
                """
                SELECT DISTINCT contents AS contents_code, density_units
                FROM silo_status
                WHERE snapshot_date = :sd AND contents IS NOT NULL AND contents <> ''
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        contents_map: dict[str, int] = {}
        for c in contents_rows:
            code = c["contents_code"] or "UNKNOWN"
            row = conn.execute(
                text("SELECT contents_key FROM silo_dim_contents WHERE contents_code = :c"),
                {"c": code},
            ).fetchone()
            if row:
                contents_map[code] = int(row[0])
            else:
                r = conn.execute(
                    text(
                        "INSERT INTO silo_dim_contents (contents_code, density_units) VALUES (:c, :d)"
                    ),
                    {"c": code, "d": c.get("density_units")},
                )
                contents_map[code] = int(r.lastrowid)

        unk_row = conn.execute(
            text("SELECT contents_key FROM silo_dim_contents WHERE contents_code = 'UNKNOWN'")
        ).fetchone()
        unknown_contents_key = int(unk_row[0]) if unk_row else 1
        contents_map.setdefault("UNKNOWN", unknown_contents_key)

        # ── 3. Resolve silo_dim_alarm ───────────────────────────────────────
        alarm_rows = conn.execute(
            text(
                "SELECT DISTINCT alarm_condition FROM silo_status WHERE snapshot_date = :sd"
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        alarm_map: dict[str, int] = {}
        for a in alarm_rows:
            code = (a["alarm_condition"] or "NONE").strip() or "NONE"
            if code in alarm_map:
                continue
            row = conn.execute(
                text("SELECT alarm_key FROM silo_dim_alarm WHERE alarm_code = :c"),
                {"c": code},
            ).fetchone()
            if row:
                alarm_map[code] = int(row[0])
            else:
                upper = code.upper()
                severity = 2 if "ALARM" in upper else (1 if "WARN" in upper else 0)
                label = ("ALARM" if severity == 2 else ("WARNING" if severity == 1 else "NONE"))
                r = conn.execute(
                    text(
                        """
                        INSERT INTO silo_dim_alarm (alarm_code, severity_level, severity_label)
                        VALUES (:c, :s, :l)
                        """
                    ),
                    {"c": code, "s": severity, "l": label},
                )
                alarm_map[code] = int(r.lastrowid)

        none_row = conn.execute(
            text("SELECT alarm_key FROM silo_dim_alarm WHERE alarm_code = 'NONE'")
        ).fetchone()
        none_alarm_key = int(none_row[0]) if none_row else 1
        alarm_map.setdefault("NONE", none_alarm_key)

        # ── 4. Load fact_silo_status ────────────────────────────────────────
        raw_rows = conn.execute(
            text(
                """
                SELECT measurement_time, snapshot_date, vessel_name, contents,
                    product_density, product_volume, product_weight, product_height,
                    headroom_volume, headroom_weight, headroom_height,
                    measurement_in_feet, measurement_in_meters, percent_full,
                    alarm_condition, source_file
                FROM silo_status
                WHERE snapshot_date = :sd
                """
            ),
            {"sd": snapshot_date},
        ).mappings().all()

        fact_rows = []
        for r in raw_rows:
            vk = vessel_map.get(r["vessel_name"] or "")
            if vk is None:
                continue
            ck = contents_map.get(r["contents"] or "UNKNOWN", unknown_contents_key)
            ac = (r["alarm_condition"] or "NONE").strip() or "NONE"
            ak = alarm_map.get(ac, none_alarm_key)
            fact_rows.append(
                {
                    "measurement_time": r["measurement_time"],
                    "snapshot_date": r["snapshot_date"],
                    "time_key": r["snapshot_date"],
                    "vessel_key": vk,
                    "contents_key": ck,
                    "alarm_key": ak,
                    "product_density": r["product_density"],
                    "product_volume": r["product_volume"],
                    "product_weight": r["product_weight"],
                    "product_height": r["product_height"],
                    "headroom_volume": r["headroom_volume"],
                    "headroom_weight": r["headroom_weight"],
                    "headroom_height": r["headroom_height"],
                    "measurement_in_feet": r["measurement_in_feet"],
                    "measurement_in_meters": r["measurement_in_meters"],
                    "percent_full": r["percent_full"],
                    "source_file": r["source_file"],
                }
            )

        fact_inserted = 0
        if fact_rows:
            res = conn.execute(
                text(
                    """
                    INSERT IGNORE INTO fact_silo_status (
                        measurement_time, snapshot_date, time_key,
                        vessel_key, contents_key, alarm_key,
                        product_density, product_volume, product_weight, product_height,
                        headroom_volume, headroom_weight, headroom_height,
                        measurement_in_feet, measurement_in_meters, percent_full, source_file
                    ) VALUES (
                        :measurement_time, :snapshot_date, :time_key,
                        :vessel_key, :contents_key, :alarm_key,
                        :product_density, :product_volume, :product_weight, :product_height,
                        :headroom_volume, :headroom_weight, :headroom_height,
                        :measurement_in_feet, :measurement_in_meters, :percent_full, :source_file
                    )
                    """
                ),
                fact_rows,
            )
            fact_inserted = int(res.rowcount or 0)

        # ── 5a. silo_agg_inventory_current ──────────────────────────────────
        # Use DELETE + INSERT (no alias ON DUPLICATE KEY — not valid with SELECT)
        conn.execute(
            text(
                """
                DELETE FROM silo_agg_inventory_current
                WHERE vessel_key IN (
                    SELECT DISTINCT vessel_key FROM fact_silo_status
                    WHERE snapshot_date = :sd
                )
                """
            ),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_inventory_current
                    (vessel_key, vessel_name, site, contents_code,
                     last_measurement_time, percent_full, product_weight,
                     product_height, alarm_code, severity_level, refreshed_at)
                SELECT
                    f.vessel_key, v.vessel_name, v.site, c.contents_code,
                    f.measurement_time, f.percent_full, f.product_weight,
                    f.product_height, a.alarm_code, a.severity_level, UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel   v ON v.vessel_key   = f.vessel_key
                JOIN silo_dim_contents c ON c.contents_key = f.contents_key
                JOIN silo_dim_alarm    a ON a.alarm_key    = f.alarm_key
                WHERE f.measurement_time = (
                    SELECT MAX(f2.measurement_time)
                    FROM fact_silo_status f2
                    WHERE f2.vessel_key = f.vessel_key
                )
                  AND f.snapshot_date = :sd
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5b. silo_agg_inventory_daily ────────────────────────────────────
        conn.execute(
            text("DELETE FROM silo_agg_inventory_daily WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_inventory_daily
                    (snapshot_date, contents_code, reading_count,
                     avg_percent_full, min_percent_full, max_percent_full,
                     total_product_weight, avg_product_weight, refreshed_at)
                SELECT
                    f.snapshot_date, c.contents_code, COUNT(*),
                    AVG(f.percent_full), MIN(f.percent_full), MAX(f.percent_full),
                    SUM(f.product_weight), AVG(f.product_weight), UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_contents c ON c.contents_key = f.contents_key
                WHERE f.snapshot_date = :sd
                GROUP BY f.snapshot_date, c.contents_code
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5c. silo_agg_consumption_rate ───────────────────────────────────
        conn.execute(
            text("DELETE FROM silo_agg_consumption_rate WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_consumption_rate
                    (vessel_key, snapshot_date, vessel_name, contents_code,
                     product_weight, prev_day_weight, weight_delta,
                     avg_7d_delta, days_to_empty, refreshed_at)
                SELECT
                    cur.vessel_key,
                    :sd AS snapshot_date,
                    v.vessel_name,
                    c.contents_code,
                    cur.avg_weight AS product_weight,
                    prev.avg_weight AS prev_day_weight,
                    (cur.avg_weight - COALESCE(prev.avg_weight, cur.avg_weight)) AS weight_delta,
                    NULL AS avg_7d_delta,
                    CASE
                        WHEN (cur.avg_weight - COALESCE(prev.avg_weight, cur.avg_weight)) < 0
                        THEN ROUND(ABS(cur.avg_weight / NULLIF(
                            cur.avg_weight - COALESCE(prev.avg_weight, cur.avg_weight), 0)), 1)
                        ELSE NULL
                    END AS days_to_empty,
                    UTC_TIMESTAMP()
                FROM (
                    SELECT vessel_key,
                           AVG(product_weight) AS avg_weight,
                           MAX(contents_key)   AS contents_key
                    FROM fact_silo_status
                    WHERE snapshot_date = :sd
                    GROUP BY vessel_key
                ) cur
                JOIN silo_dim_vessel   v ON v.vessel_key   = cur.vessel_key
                JOIN silo_dim_contents c ON c.contents_key = cur.contents_key
                LEFT JOIN (
                    SELECT vessel_key, AVG(product_weight) AS avg_weight
                    FROM fact_silo_status
                    WHERE snapshot_date = DATE_SUB(:sd, INTERVAL 1 DAY)
                    GROUP BY vessel_key
                ) prev ON prev.vessel_key = cur.vessel_key
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5d. silo_agg_alarm_stats ─────────────────────────────────────────
        conn.execute(
            text("DELETE FROM silo_agg_alarm_stats WHERE snapshot_date = :sd"),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_alarm_stats
                    (vessel_key, snapshot_date, vessel_name,
                     alarm_code, severity_level, alarm_count, refreshed_at)
                SELECT
                    f.vessel_key, f.snapshot_date, v.vessel_name,
                    a.alarm_code, a.severity_level, COUNT(*), UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel v ON v.vessel_key = f.vessel_key
                JOIN silo_dim_alarm  a ON a.alarm_key  = f.alarm_key
                WHERE f.snapshot_date = :sd
                GROUP BY f.vessel_key, f.snapshot_date, v.vessel_name,
                         a.alarm_code, a.severity_level
                """
            ),
            {"sd": snapshot_date},
        )

        # ── 5e. silo_agg_silo_utilization ───────────────────────────────────
        conn.execute(
            text(
                """
                DELETE FROM silo_agg_silo_utilization
                WHERE ym = DATE_FORMAT(:sd, '%Y-%m')
                """
            ),
            {"sd": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO silo_agg_silo_utilization
                    (vessel_key, ym, vessel_name, site, reading_count,
                     avg_percent_full, min_percent_full, max_percent_full,
                     days_above_80pct, days_below_20pct, refreshed_at)
                SELECT
                    f.vessel_key,
                    DATE_FORMAT(f.snapshot_date, '%Y-%m') AS ym,
                    v.vessel_name, v.site,
                    COUNT(*),
                    AVG(f.percent_full), MIN(f.percent_full), MAX(f.percent_full),
                    SUM(CASE WHEN f.percent_full > 80 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN f.percent_full < 20 THEN 1 ELSE 0 END),
                    UTC_TIMESTAMP()
                FROM fact_silo_status f
                JOIN silo_dim_vessel v ON v.vessel_key = f.vessel_key
                WHERE DATE_FORMAT(f.snapshot_date, '%Y-%m') = DATE_FORMAT(:sd, '%Y-%m')
                GROUP BY f.vessel_key, DATE_FORMAT(f.snapshot_date, '%Y-%m'),
                         v.vessel_name, v.site
                """
            ),
            {"sd": snapshot_date},
        )


    return {
        "vessels_resolved": len(vessel_map),
        "fact_rows_inserted": fact_inserted,
    }


# ---------------------------------------------------------------------------
# Silos — serving-layer API endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/api/silos/inventory-current",
    summary="Silos Current Inventory",
    description=(
        "Returns the latest inventory snapshot per vessel from "
        "silo_agg_inventory_current, ordered by site then vessel name."
    ),
)
async def silos_inventory_current() -> JSONResponse:
    """Return per-vessel current inventory from the serving-layer aggregate."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT vessel_key, vessel_name, site, contents_code,
                       last_measurement_time, percent_full, product_weight,
                       product_height, alarm_code, severity_level, refreshed_at
                FROM silo_agg_inventory_current
                ORDER BY site, vessel_name
                """
            )
        ).mappings().all()

    def _ser(v):
        """Serialize datetimes and Decimals."""
        import decimal
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return float(v)
        return v

    return JSONResponse(
        content={"data": [{k: _ser(v) for k, v in row.items()} for row in rows]}
    )


@router.get(
    "/api/silos/inventory-daily",
    summary="Silos Daily Inventory Trend",
    description=(
        "Returns daily aggregate inventory from silo_agg_inventory_daily "
        "for the last N days (default 30). Param: days (int, 1–365)."
    ),
)
async def silos_inventory_daily(days: int = 30) -> JSONResponse:
    """Return daily inventory trend from the serving-layer aggregate."""
    days = max(1, min(days, 365))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT snapshot_date, contents_code, reading_count,
                       avg_percent_full, min_percent_full, max_percent_full,
                       total_product_weight, avg_product_weight
                FROM silo_agg_inventory_daily
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                ORDER BY snapshot_date, contents_code
                """
            ),
            {"days": days},
        ).mappings().all()

    def _ser(v):
        import decimal
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return float(v)
        return v

    return JSONResponse(
        content={"data": [{k: _ser(v) for k, v in row.items()} for row in rows]}
    )


@router.get(
    "/api/silos/consumption-rate",
    summary="Silos Consumption / Burn Rate",
    description=(
        "Returns per-vessel daily consumption rate from "
        "silo_agg_consumption_rate for the last N days (default 30)."
    ),
)
async def silos_consumption_rate(days: int = 30) -> JSONResponse:
    """Return vessel burn-rate data from the serving-layer aggregate."""
    days = max(1, min(days, 365))
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT vessel_key, snapshot_date, vessel_name, contents_code,
                       product_weight, prev_day_weight, weight_delta,
                       avg_7d_delta, days_to_empty
                FROM silo_agg_consumption_rate
                WHERE snapshot_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
                ORDER BY vessel_name, snapshot_date
                """
            ),
            {"days": days},
        ).mappings().all()

    def _ser(v):
        import decimal
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return float(v)
        return v

    return JSONResponse(
        content={"data": [{k: _ser(v) for k, v in row.items()} for row in rows]}
    )


# ---------------------------------------------------------------------------
# Not in XFCMA Upload & CRUD
# ---------------------------------------------------------------------------

def _row_to_not_in_xfcma(row) -> NotInXfcmaRow:
    """Map a SQLAlchemy row to a NotInXfcmaRow model."""
    return NotInXfcmaRow(
        id=int(row.id),
        report_datetime=row.report_datetime,
        product_code=row.product_code,
        manu_order=row.manu_order,
        item=int(row.item),
        pallet=row.pallet,
        location=row.location,
        rolls=int(row.rolls),
        length=int(row.length),
        weight=int(row.weight),
        grade=row.grade,
        last_in_date=row.last_in_date,
        created_at_utc=row.created_at_utc,
        source_file=row.source_file,
    )


@router.get(
    "/not-in-xfcma",
    response_class=HTMLResponse,
    summary="Upload not in XFCMA Page",
    description=(
        "Maintenance page to upload, view, update, and delete records in the "
        "not_in_xfcma table."
    ),
)
async def not_in_xfcma_page(request: Request) -> HTMLResponse:
    """Render the not_in_xfcma upload and management page."""
    return templates.TemplateResponse(
        "maintenance/not_in_xfcma.html",
        {"request": request, "active_page": "not_in_xfcma"},
    )


def _parse_not_in_xfcma_text_pdf(pdf_path: Path) -> list[dict]:
    """Fallback parser for text-line based 'Plt In As400 ... not In XFCMA' PDFs."""
    parsed: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text_content = page.extract_text() or ""
            for raw_line in text_content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith(("TOTAL", "COUNT", "Report:")):
                    continue
                if "Plt In As400" in line or "Product Code" in line:
                    continue
                if "Order#" in line or line.startswith("____"):
                    continue

                match = _XFCMA_LINE_RE.match(line)
                if not match:
                    continue

                (
                    product_code,
                    manu_order,
                    item,
                    pallet,
                    location,
                    rolls,
                    length,
                    weight,
                    grade,
                    last_in_date,
                ) = match.groups()

                try:
                    parsed_date = datetime.strptime(last_in_date, "%y/%m/%d").date()
                except ValueError:
                    continue

                parsed.append(
                    {
                        "product_code": product_code,
                        "order": manu_order,
                        "item": item,
                        "pallet_no": pallet,
                        "loc": location,
                        "rolls": rolls.replace(",", ""),
                        "length": length.replace(",", ""),
                        "weight": weight.replace(",", ""),
                        "grade": (grade or "")[:5],
                        "last_in_date": parsed_date,
                    }
                )

    return parsed


@router.post(
    "/api/not-in-xfcma/upload",
    summary="Upload not_in_xfcma PDF",
    description=(
        "Upload one or more QPQUPRFIL PDF reports, parse rows, and insert the "
        "extracted records into not_in_xfcma."
    ),
)
async def not_in_xfcma_upload_pdf(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Parse uploaded PDFs and insert rows into not_in_xfcma."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one PDF file")

    all_insert_params: list[dict] = []
    file_summaries: list[dict] = []
    invalid_files: list[str] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            invalid_files.append(filename or "(unnamed)")
            continue

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                content = await upload.read()
                tmp.write(content)
                temp_path = Path(tmp.name)

            report_dt, parsed_rows = _parse_pdf(temp_path)
            if not parsed_rows:
                parsed_rows = _parse_not_in_xfcma_text_pdf(temp_path)
            if report_dt is None:
                report_dt = datetime.now()

            if not parsed_rows:
                file_summaries.append({"file": filename, "inserted": 0, "detail": "No rows found"})
                continue

            file_insert_count = 0
            for row in parsed_rows:
                trans_date = _as400_date(row.get("trans_date", ""))
                if trans_date is None and row.get("last_in_date") is not None:
                    trans_date = row.get("last_in_date")
                length_raw = (row.get("length") or "").strip()
                rolls_raw = (row.get("rolls") or "").strip()
                weight_raw = (row.get("weight") or "").strip()
                item_raw = (row.get("item") or "").strip()

                try:
                    length_val = int(float(length_raw)) if length_raw else 0
                except ValueError:
                    length_val = 0

                try:
                    rolls_val = int(float(rolls_raw)) if rolls_raw else 0
                except ValueError:
                    rolls_val = 0

                try:
                    weight_val = int(float(weight_raw)) if weight_raw else 0
                except ValueError:
                    weight_val = 0

                try:
                    item_val = int(float(item_raw)) if item_raw else 0
                except ValueError:
                    item_val = 0

                all_insert_params.append(
                    {
                        "report_datetime": report_dt,
                        "product_code": (row.get("product_code") or "").strip(),
                        "manu_order": (row.get("order") or "").strip(),
                        "item": item_val,
                        "pallet": (row.get("pallet_no") or "").strip(),
                        "location": (row.get("loc") or "").strip(),
                        "rolls": rolls_val,
                        "length": length_val,
                        "weight": weight_val,
                        "grade": (row.get("grade") or "").strip(),
                        "last_in_date": trans_date or report_dt.date(),
                        "source_file": filename,
                    }
                )
                file_insert_count += 1

            file_summaries.append(
                {
                    "file": filename,
                    "inserted": file_insert_count,
                    "report_datetime": report_dt.isoformat(sep=" "),
                }
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if invalid_files:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are allowed. Invalid files: {', '.join(invalid_files)}",
        )

    if not all_insert_params:
        raise HTTPException(status_code=400, detail="No data rows found in uploaded PDF files")

    # Delete existing rows for each source filename so the same file can be re-uploaded
    unique_filenames = list({p["source_file"] for p in all_insert_params})

    with _engine.begin() as conn:
        for fname in unique_filenames:
            conn.execute(
                text("DELETE FROM not_in_xfcma WHERE source_file = :fname"),
                {"fname": fname},
            )

        result = conn.execute(
            text(
                """
                INSERT INTO not_in_xfcma
                (report_datetime, product_code, manu_order, item, pallet,
                 location, rolls, length, weight, grade, last_in_date, created_at_utc,
                 source_file)
                VALUES
                (:report_datetime, :product_code, :manu_order, :item, :pallet,
                 :location, :rolls, :length, :weight, :grade, :last_in_date, NOW(),
                 :source_file)
                """
            ),
            all_insert_params,
        )
        inserted_count = int(result.rowcount or 0)

    return JSONResponse(
        content={
            "message": f"Inserted {inserted_count} rows from {len(file_summaries)} file(s)",
            "inserted": inserted_count,
            "files": file_summaries,
        }
    )


@router.get(
    "/api/not-in-xfcma",
    response_model=list[NotInXfcmaRow],
    summary="List not_in_xfcma rows",
    description=(
        "Returns not_in_xfcma rows ordered by report_datetime desc and id desc. "
        "Optional filters for product_code and date range."
    ),
)
async def not_in_xfcma_list(
    product_code: Optional[str] = Query(None, description="Filter by product_code"),
    date_from: Optional[str] = Query(None, description="report_datetime >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="report_datetime <= (YYYY-MM-DD)"),
    limit: int = Query(500, ge=1, le=5000, description="Maximum rows to return"),
) -> list[NotInXfcmaRow]:
    """Return not_in_xfcma rows with optional filters."""
    with _engine.connect() as conn:
        where_clauses = []
        params = {}

        if product_code:
            where_clauses.append("product_code = :product_code")
            params["product_code"] = product_code

        if date_from:
            where_clauses.append("DATE(report_datetime) >= :date_from")
            params["date_from"] = date_from

        if date_to:
            where_clauses.append("DATE(report_datetime) <= :date_to")
            params["date_to"] = date_to

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        rows = conn.execute(
            text(f"""
                SELECT
                    id, report_datetime, product_code, manu_order, item, pallet,
                    location, rolls, length, weight, grade, last_in_date, created_at_utc,
                    source_file
                FROM not_in_xfcma
                {where}
                ORDER BY report_datetime DESC, id DESC
                LIMIT :limit
            """),
            {**params, "limit": limit},
        ).fetchall()

        return [_row_to_not_in_xfcma(row) for row in rows]


@router.post(
    "/api/not-in-xfcma",
    response_model=NotInXfcmaRow,
    summary="Create not_in_xfcma row",
    description="Create a new not_in_xfcma record.",
)
async def not_in_xfcma_create(body: NotInXfcmaCreateRequest) -> NotInXfcmaRow:
    """Create a new not_in_xfcma row."""
    with _engine.connect() as conn:
        result = conn.execute(
            text("""
                INSERT INTO not_in_xfcma
                (report_datetime, product_code, manu_order, item, pallet,
                 location, rolls, length, weight, grade, last_in_date)
                VALUES
                (:report_datetime, :product_code, :manu_order, :item, :pallet,
                 :location, :rolls, :length, :weight, :grade, :last_in_date)
            """),
            {
                "report_datetime": body.report_datetime,
                "product_code": body.product_code,
                "manu_order": body.manu_order,
                "item": body.item,
                "pallet": body.pallet,
                "location": body.location,
                "rolls": body.rolls,
                "length": body.length,
                "weight": body.weight,
                "grade": body.grade,
                "last_in_date": body.last_in_date,
            },
        )
        new_id = result.lastrowid
        conn.commit()

        # Fetch the newly created row
        row = conn.execute(
            text("""
                SELECT
                    id, report_datetime, product_code, manu_order, item, pallet,
                    location, rolls, length, weight, grade, last_in_date, created_at_utc,
                    source_file
                FROM not_in_xfcma
                WHERE id = :id
            """),
            {"id": new_id},
        ).fetchone()

        return _row_to_not_in_xfcma(row)


@router.put(
    "/api/not-in-xfcma/{row_id}",
    response_model=NotInXfcmaRow,
    summary="Update not_in_xfcma row",
    description="Update an existing not_in_xfcma record.",
)
async def not_in_xfcma_update(row_id: int, body: NotInXfcmaUpdateRequest) -> NotInXfcmaRow:
    """Update a not_in_xfcma row."""
    updates = []
    params = {"id": row_id}

    if body.report_datetime is not None:
        updates.append("report_datetime = :report_datetime")
        params["report_datetime"] = body.report_datetime
    if body.product_code is not None:
        updates.append("product_code = :product_code")
        params["product_code"] = body.product_code
    if body.manu_order is not None:
        updates.append("manu_order = :manu_order")
        params["manu_order"] = body.manu_order
    if body.item is not None:
        updates.append("item = :item")
        params["item"] = body.item
    if body.pallet is not None:
        updates.append("pallet = :pallet")
        params["pallet"] = body.pallet
    if body.location is not None:
        updates.append("location = :location")
        params["location"] = body.location
    if body.rolls is not None:
        updates.append("rolls = :rolls")
        params["rolls"] = body.rolls
    if body.length is not None:
        updates.append("length = :length")
        params["length"] = body.length
    if body.weight is not None:
        updates.append("weight = :weight")
        params["weight"] = body.weight
    if body.grade is not None:
        updates.append("grade = :grade")
        params["grade"] = body.grade
    if body.last_in_date is not None:
        updates.append("last_in_date = :last_in_date")
        params["last_in_date"] = body.last_in_date

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    with _engine.connect() as conn:
        conn.execute(
            text(f"""
                UPDATE not_in_xfcma
                SET {', '.join(updates)}
                WHERE id = :id
            """),
            params,
        )
        conn.commit()

        row = conn.execute(
            text("""
                SELECT
                    id, report_datetime, product_code, manu_order, item, pallet,
                    location, rolls, length, weight, grade, last_in_date, created_at_utc,
                    source_file
                FROM not_in_xfcma
                WHERE id = :id
            """),
            {"id": row_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Row with id {row_id} not found")

        return _row_to_not_in_xfcma(row)


@router.delete(
    "/api/not-in-xfcma/{row_id}",
    response_model=NotInXfcmaDeleteResponse,
    summary="Delete not_in_xfcma row",
    description="Delete a not_in_xfcma record by id.",
)
async def not_in_xfcma_delete(row_id: int) -> NotInXfcmaDeleteResponse:
    """Delete a not_in_xfcma row."""
    with _engine.connect() as conn:
        result = conn.execute(
            text("DELETE FROM not_in_xfcma WHERE id = :id"),
            {"id": row_id},
        )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Row with id {row_id} not found")

        return NotInXfcmaDeleteResponse(
            id=row_id,
            message=f"Row {row_id} deleted successfully",
        )
