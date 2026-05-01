"""
routers/maintenance/lmi.py — Logistics Management Index (LMI) document analysis.

Provides AI-powered analysis of monthly LMI reports using a local Ollama
instance running ``deepseek-r1:8b``.  Source documents live in::

    raw_data/lmi/          ← monthly .txt files (one per LMI report)
    raw_data/lmi_scores.csv ← pre-extracted LMI scores for the trend chart

Features
--------
- Bullet-point takeaways for a single document (streamed, < 2 s to first token).
- Cross-month 5-question analysis for the Briefing page (streamed).
- ``<think>`` reasoning blocks produced by deepseek-r1 are stripped from the
  output before streaming so the client only receives the final answer.

Routes:
    GET  /lmi                   — LMI document analysis page
    POST /lmi/analyze           — Stream bullet-point takeaways for one document
    GET  /lmi/briefing-analysis — Stream 5-question cross-month analysis
"""

import csv
import json
import re
from pathlib import Path

import httpx
import pdfplumber
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directory containing LMI source documents
_LMI_DIR = Path(__file__).parent.parent.parent / "raw_data" / "lmi"

# Pre-extracted LMI scores CSV used for the trend line chart
_LMI_SCORES_CSV = Path(__file__).parent.parent.parent / "raw_data" / "lmi_scores.csv"

# File extensions the analysis pipeline accepts
_SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".txt", ".csv"}

# Ollama API configuration
_OLLAMA_URL   = "http://localhost:11434/api/generate"
_OLLAMA_MODEL = "deepseek-r1:8b"

# Maximum document characters forwarded to the model (fits within context window)
_MAX_TEXT_CHARS = 12_000

# Month abbreviation → month number (for filename parsing)
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Pattern to extract the LMI composite score from report text
_SCORE_RE = re.compile(r"LMI[®\s]{0,5}at\s+([\d]+\.[\d]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for the single-document LMI analyze endpoint."""

    filename: str   # basename only — no directory traversal allowed


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_text(path: Path) -> str:
    """Extract plain text from a supported document file.

    Supported formats:
    - ``.pdf``  — extracted via pdfplumber (text layer only, no OCR).
    - ``.txt``  / ``.csv`` — read directly as UTF-8.
    - ``.docx`` / ``.xlsx`` — placeholder; returns a not-implemented message.

    Args:
        path: Absolute path to the document file.

    Returns:
        Up to ``_MAX_TEXT_CHARS`` characters of extracted text.
    """
    ext = path.suffix.lower()

    if ext == ".pdf":
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
        return "\n".join(pages)[:_MAX_TEXT_CHARS]

    if ext in (".txt", ".csv"):
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_TEXT_CHARS]

    # DOCX / XLSX extraction not yet implemented
    return f"[File type {ext} extraction not yet implemented]"


def _build_prompt(filename: str, document_text: str) -> str:
    """Construct the Ollama prompt for bullet-point takeaways.

    Args:
        filename:      Name of the document (for model context).
        document_text: Extracted text body of the document.

    Returns:
        A complete prompt string ready to send to Ollama.
    """
    return (
        "Read the following document and provide 7-10 concise bullet point takeaways "
        "summarizing the most important findings, trends, and data points. "
        "Focus on logistics, supply chain, and economic metrics. "
        "Format as markdown bullet points using the • character as the prefix. "
        "Do not include any preamble, explanation, or closing remarks — "
        "start directly with the first bullet point.\n\n"
        f"Document: {filename}\n"
        "---\n"
        f"{document_text}\n"
        "---\n"
        "Bullet point takeaways:"
    )


async def _stream_ollama(prompt: str):
    """Async generator that streams text chunks from Ollama.

    Strips ``<think>…</think>`` reasoning blocks produced by deepseek-r1
    before yielding to the HTTP response, so the client only receives the
    final answer text.

    Ollama streams newline-delimited JSON:
        ``{"response": "chunk", "done": false}``

    Args:
        prompt: Full prompt string to send to the model.

    Yields:
        Decoded text fragments suitable for a StreamingResponse.
    """
    in_think  = False
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

                # ── State machine: strip <think>…</think> blocks ─────────────
                for char in chunk:
                    if in_think:
                        think_buf += char
                        if think_buf.endswith("</think>"):
                            in_think  = False
                            think_buf = ""
                    else:
                        think_buf += char
                        if "<think>" in think_buf:
                            # Yield everything before the <think> tag
                            pre = think_buf[: think_buf.index("<think>")]
                            if pre:
                                yield pre
                            think_buf = ""
                            in_think  = True
                        elif len(think_buf) > 20:
                            # Safe to yield — no partial <think> tag forming
                            yield think_buf
                            think_buf = ""

                # Flush safe buffer at end of each Ollama chunk
                if not in_think and think_buf and "<" not in think_buf:
                    yield think_buf
                    think_buf = ""


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get(
    "/lmi",
    response_class=HTMLResponse,
    summary="LMI Document Analysis",
    description=(
        "Lists all documents in ``raw_data/lmi/`` and provides AI-powered "
        "bullet-point takeaways for each via local Ollama (deepseek-r1:8b). "
        "Also displays an LMI composite score trend line chart."
    ),
)
async def lmi_page(request: Request) -> HTMLResponse:
    """Render the LMI document analysis and trend chart page."""
    files = sorted(
        f.name for f in _LMI_DIR.glob("*") if f.suffix.lower() in _SUPPORTED_EXTS
    )

    # Pre-select the current month's file; fall back to the most recent file
    from datetime import datetime
    month_str    = datetime.now().strftime("%B %Y")   # e.g. "April 2026"
    default_file = next(
        (f for f in files if month_str in f),
        files[-1] if files else None,
    )

    # Load historical LMI scores for the line chart
    lmi_scores: list[dict] = []
    if _LMI_SCORES_CSV.exists():
        with _LMI_SCORES_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lmi_scores.append({"date": row["date"], "lmi_score": float(row["lmi_score"])})

    return templates.TemplateResponse(
        "maintenance/lmi.html",
        {
            "request":      request,
            "active_page":  "lmi",
            "files":        files,
            "default_file": default_file,
            "lmi_scores":   lmi_scores,
        },
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@router.post(
    "/lmi/analyze",
    summary="Analyze an LMI Document with Ollama",
    description=(
        "Reads the specified file from ``raw_data/lmi/``, extracts its text, "
        "and streams 7–10 bullet-point takeaways from local Ollama "
        "``deepseek-r1:8b``.  ``<think>`` reasoning blocks are stripped before "
        "streaming so the client only receives the final bullet points."
    ),
)
async def lmi_analyze(body: AnalyzeRequest) -> StreamingResponse:
    """Stream AI-generated bullet-point takeaways for a single LMI document.

    Validates the filename to prevent path traversal before reading the file.

    Raises:
        HTTPException 404: File not found or extension not supported.
    """
    # Prevent path traversal — accept basename only
    filename = Path(body.filename).name
    path     = _LMI_DIR / filename
    if not path.exists() or path.suffix.lower() not in _SUPPORTED_EXTS:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    document_text = _extract_text(path)
    prompt        = _build_prompt(filename, document_text)

    return StreamingResponse(
        _stream_ollama(prompt),
        media_type="text/plain; charset=utf-8",
    )


@router.get(
    "/lmi/briefing-analysis",
    summary="Cross-Month LMI Analysis for Briefing Page",
    description=(
        "Reads all LMI ``.txt`` files in ``raw_data/lmi/``, builds a chronological "
        "15-month timeline with extracted LMI scores, and streams a structured "
        "5-question analysis (trend arc, turning points, unusual readings, "
        "Q2-2026 signal, AMJK action item) from ``deepseek-r1:8b`` via Ollama."
    ),
)
async def lmi_briefing_analysis() -> StreamingResponse:
    """Stream a full cross-month LMI market analysis for the Operations Briefing page.

    Each monthly ``.txt`` file is parsed to extract:
    - Month-year identifier (derived from filename, e.g. ``lmi_apr_2025.txt`` → 2025-04)
    - LMI composite score (regex match on "LMI at XX.X")
    - First 5 substantial paragraphs (≥ 100 chars) as the body summary

    The timeline is assembled chronologically and sent as a single prompt
    with strict evidence-citation instructions to minimise hallucination.
    """
    records = []
    for f in sorted(_LMI_DIR.glob("*.txt")):
        stem  = f.stem.lower()
        match = re.match(r"lmi_([a-z]+)_?(\d{4})", stem)
        if not match:
            continue
        month_num = _MONTH_MAP.get(match.group(1)[:3])
        if not month_num:
            continue

        month_id   = f"{match.group(2)}-{month_num:02d}"
        body_text  = f.read_text(encoding="utf-8", errors="ignore")
        score_match = _SCORE_RE.search(body_text)
        score      = score_match.group(1) if score_match else "?"
        paragraphs = [ln.strip() for ln in body_text.splitlines() if len(ln.strip()) > 100]
        summary    = " | ".join(paragraphs[:5])[:1200]
        records.append((month_id, score, summary))

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
