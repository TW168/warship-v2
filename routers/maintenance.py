"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
  GET /maintenance/input            — data entry form
  GET /maintenance/frt-validation   — Freight ¢/lb by Product Code validation tool
  GET /maintenance/freight-audit    — Freight ¢/lb calculation audit page
  GET /api/maintenance/freight-audit — JSON audit data
  GET /maintenance/lmi              — LMI document analysis page
  POST /maintenance/lmi/analyze     — Stream AI bullet-point takeaways via Ollama
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pdfplumber
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import text

from database import connect_to_database

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
    "/input",
    response_class=HTMLResponse,
    summary="Maintenance Input page",
    description="Data entry form for warehouse and shipping maintenance records.",
)
async def maintenance_input(request: Request) -> HTMLResponse:
    """Render the maintenance data entry form."""
    return templates.TemplateResponse(
        "maintenance/input.html",
        {"request": request, "active_page": "maintenance"},
    )


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
