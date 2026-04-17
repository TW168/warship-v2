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
from schemas.shipping_status import (
    ShippingStatusCreateRequest,
    ShippingStatusDeleteResponse,
    ShippingStatusRow,
    ShippingStatusUpdateRequest,
)

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
