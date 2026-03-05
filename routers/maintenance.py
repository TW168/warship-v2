"""
routers/maintenance.py — Maintenance sub-page routes.

Handles:
  GET /maintenance/input            — data entry form
  GET /maintenance/frt-validation   — Freight ¢/lb by Product Code validation tool
  GET /maintenance/lmi              — LMI document analysis page
  POST /maintenance/lmi/analyze     — Stream AI bullet-point takeaways via Ollama
"""

import json
import re
from pathlib import Path

import httpx
import pdfplumber
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# Directory containing LMI source documents
_LMI_DIR = Path(__file__).parent.parent / "raw_data" / "lmi"

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
    return templates.TemplateResponse(
        "maintenance/lmi.html",
        {"request": request, "active_page": "lmi", "files": files},
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
