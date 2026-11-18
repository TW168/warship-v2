"""OpenRouter model test page and chat endpoint."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import TypedDict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI, OpenAIError
import markdown
import pypdfium2 as pdfium

from logging_config import get_router_logger
from schemas.openrouter import (
    OpenRouterChatRequest,
    OpenRouterChatResponse,
    OpenRouterLmiSummaryRequest,
    OpenRouterLmiSummaryResponse,
)
from .lmi import _LMI_DIR, _extract_text

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")
logger = get_router_logger("maintenance.openrouter")

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL_ID = "openrouter/auto"
_MAX_PROMPT_CHARS = 4_000
_MAX_COMPLETION_TOKENS = 1_200
_MAX_LMI_SUMMARY_TOKENS = 4_096
_MAX_LMI_CHUNK_SUMMARY_TOKENS = 1_200
_MAX_LMI_RETRY_TOKENS = 8_192
_SUPPORTED_LMI_EXTENSIONS = {".pdf", ".txt", ".csv"}
_OCR_RENDER_SCALE = 2
_OCR_MAX_PAGES = 50
_OCR_MAX_PIXELS_PER_PAGE = 15_000_000
_OCR_PAGE_TIMEOUT_SECONDS = 20
_OCR_MAX_FILE_BYTES = 25 * 1024 * 1024
_SUMMARY_CHUNK_CHARS = 24_000
_SUMMARY_REDUCTION_GROUP_SIZE = 8
_SUMMARY_VERSION = 2
_PREVIOUS_SUMMARY_VERSION = 1
_SUMMARY_ID_RE = re.compile(r"[0-9a-f]{64}\Z")


class _CachedLmiSummary(TypedDict):
    """Validated cached summary data returned to the summary endpoint."""

    summary_id: str
    models: list[str]
    answer: str
    created_at: str


class _SavedLmiSummary(TypedDict):
    """Saved summary metadata rendered in the page's download list."""

    summary_id: str
    document: str
    models: list[str]
    created_at: str


class _MarkdownPlainTextParser(HTMLParser):
    """Convert Markdown-generated HTML blocks into readable plain text."""

    _BLOCK_TAGS = {
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ol",
        "p",
        "pre",
        "table",
        "ul",
    }

    def __init__(self) -> None:
        """Initialize the output buffer and table-cell counter."""
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.table_cell_count = 0
        self.list_depth = 0
        self.pre_depth = 0

    def _append_newline(self) -> None:
        """Append a newline unless the output already ends with one."""
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Add plain-text separators and list markers for HTML block tags."""
        if tag in {"ol", "ul"}:
            self.list_depth += 1
        elif tag == "pre":
            self.pre_depth += 1
        if tag in self._BLOCK_TAGS:
            self._append_newline()
        elif tag == "br":
            self._append_newline()
        elif tag == "li":
            self._append_newline()
            self.parts.append("- ")
        elif tag == "tr":
            self.table_cell_count = 0
            self._append_newline()
        elif tag in {"td", "th"}:
            if self.table_cell_count:
                self.parts.append(" | ")
            self.table_cell_count += 1
        elif tag == "img":
            alt_text = dict(attrs).get("alt")
            if alt_text:
                self.parts.append(alt_text)

    def handle_endtag(self, tag: str) -> None:
        """Separate completed block elements and table rows."""
        if tag in self._BLOCK_TAGS or tag in {"li", "tr"}:
            self._append_newline()
        if tag in {"ol", "ul"}:
            self.list_depth -= 1
        elif tag == "pre":
            self.pre_depth -= 1

    def handle_data(self, data: str) -> None:
        """Append visible text while ignoring all markup."""
        if self.list_depth and not self.pre_depth and data.isspace():
            return
        self.parts.append(data)

    def get_text(self) -> str:
        """Return normalized plain text without Markdown or HTML markup."""
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _markdown_to_plain_text(text: str) -> str:
    """Convert a model's Markdown summary to readable plain text for display and storage."""
    renderer = markdown.Markdown(extensions=["fenced_code", "tables"])
    html_text = renderer.convert(text)
    parser = _MarkdownPlainTextParser()
    parser.feed(html_text)
    parser.close()
    return parser.get_text()


def _get_model_id() -> str:
    """Return the configured OpenRouter model ID or the Auto router default."""
    return os.getenv("OPENROUTER_MODEL_ID", "").strip() or _DEFAULT_MODEL_ID


def _list_lmi_documents() -> list[str]:
    """Return selectable, supported report files directly inside raw_data/lmi."""
    if not _LMI_DIR.is_dir():
        return []
    documents: list[str] = []
    for path in sorted(_LMI_DIR.iterdir()):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.lower() not in _SUPPORTED_LMI_EXTENSIONS
        ):
            continue
        if _read_cached_lmi_summary(path.name, path) is None:
            documents.append(path.name)
    return documents


def _resolve_lmi_document(filename: str) -> Path:
    """Validate a selected report filename and return its safe path."""
    if (
        "\x00" in filename
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(status_code=404, detail="LMI report not found.")

    path = _LMI_DIR / filename
    if (
        not path.is_file()
        or path.is_symlink()
        or path.suffix.lower() not in _SUPPORTED_LMI_EXTENSIONS
        or path.resolve().parent != _LMI_DIR.resolve()
    ):
        raise HTTPException(status_code=404, detail="LMI report not found.")
    return path


def _read_lmi_document(path: Path) -> str:
    """Extract text from a validated LMI report path."""
    text = _extract_text(path, max_chars=None)
    if not text.strip() and path.suffix.lower() == ".pdf":
        text = _ocr_pdf(path)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "No selectable text or readable text was found in the selected PDF. "
                "It may be scanned or image-only."
                if path.suffix.lower() == ".pdf"
                else "The selected report contains no extractable text."
            ),
        )
    return text


def _get_lmi_summary_id(filename: str, path: Path) -> tuple[str, str]:
    """Return a cache key and content hash for this exact source document."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    source_hash = digest.hexdigest()
    summary_id = hashlib.sha256(
        f"{filename}\0{source_hash}".encode("utf-8")
    ).hexdigest()
    return summary_id, source_hash


def _get_summary_paths(summary_id: str) -> tuple[Path, Path]:
    """Return summary text and metadata paths for a validated cache key."""
    if not _SUMMARY_ID_RE.fullmatch(summary_id):
        raise HTTPException(status_code=404, detail="Saved summary not found.")
    summary_dir = _LMI_DIR / ".summaries"
    return summary_dir / f"{summary_id}.txt", summary_dir / f"{summary_id}.json"


def _read_cached_lmi_summary(
    filename: str,
    path: Path,
) -> _CachedLmiSummary | None:
    """Read a saved summary only when its source file still has the same content."""
    try:
        summary_id, source_hash = _get_lmi_summary_id(filename, path)
        summary_path, metadata_path = _get_summary_paths(summary_id)
        if (
            summary_path.parent.is_symlink()
            or not summary_path.is_file()
            or summary_path.is_symlink()
            or not metadata_path.is_file()
            or metadata_path.is_symlink()
            or summary_path.resolve().parent != summary_path.parent.resolve()
            or metadata_path.resolve().parent != metadata_path.parent.resolve()
        ):
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read saved LMI summary for %s: %s", filename, exc)
        return None

    if not isinstance(metadata, dict):
        return None
    version = metadata.get("summary_version")
    models = metadata.get("models")
    if (
        version not in {_SUMMARY_VERSION, _PREVIOUS_SUMMARY_VERSION}
        or metadata.get("document") != filename
        or metadata.get("source_sha256") != source_hash
        or not isinstance(models, list)
        or not all(isinstance(model, str) for model in models)
    ):
        return None
    try:
        answer = _read_saved_summary_text(summary_id, metadata, summary_path)
    except OSError as exc:
        logger.exception("Could not normalize saved LMI summary for %s", filename)
        raise HTTPException(
            status_code=500,
            detail="Could not update the saved summary file to plain text.",
        ) from exc
    if not answer.strip():
        return None
    created_at = metadata.get("created_at", "")
    if not isinstance(created_at, str):
        return None
    return {
        "summary_id": summary_id,
        "models": models,
        "answer": answer,
        "created_at": created_at,
    }


def _write_text_atomically(path: Path, content: str) -> None:
    """Write one cache file atomically to avoid exposing partial summaries."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".summary-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary summary file %s", temporary_path)
        raise


def _read_saved_summary_text(
    summary_id: str,
    metadata: dict,
    summary_path: Path,
) -> str:
    """Return a cached summary, migrating older Markdown output to plain text."""
    answer = summary_path.read_text(encoding="utf-8")
    if metadata.get("summary_version") == _PREVIOUS_SUMMARY_VERSION:
        answer = _markdown_to_plain_text(answer)
        if not answer.strip():
            return ""
        metadata["summary_version"] = _SUMMARY_VERSION
        _, metadata_path = _get_summary_paths(summary_id)
        _write_text_atomically(summary_path, answer)
        _write_text_atomically(
            metadata_path,
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )
    return answer


def _save_lmi_summary(
    filename: str,
    path: Path,
    models: list[str],
    answer: str,
) -> str:
    """Persist a plain-text summary and its source/model metadata."""
    summary_id, source_hash = _get_lmi_summary_id(filename, path)
    summary_path, metadata_path = _get_summary_paths(summary_id)
    if summary_path.parent.is_symlink():
        raise OSError("The LMI summary cache directory must not be a symlink.")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "summary_version": _SUMMARY_VERSION,
        "document": filename,
        "source_sha256": source_hash,
        "models": models,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_text_atomically(summary_path, answer)
    _write_text_atomically(
        metadata_path,
        json.dumps(metadata, ensure_ascii=False, indent=2),
    )
    return summary_id


def _list_saved_summaries() -> list[_SavedLmiSummary]:
    """Return valid saved-summary metadata for display and download links."""
    summary_dir = _LMI_DIR / ".summaries"
    if not summary_dir.is_dir() or summary_dir.is_symlink():
        return []

    summaries: list[_SavedLmiSummary] = []
    for metadata_path in sorted(summary_dir.glob("*.json")):
        summary_id = metadata_path.stem
        if (
            not _SUMMARY_ID_RE.fullmatch(summary_id)
            or metadata_path.is_symlink()
        ):
            continue
        summary_path = summary_dir / f"{summary_id}.txt"
        if not summary_path.is_file() or summary_path.is_symlink():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read LMI summary metadata %s: %s", summary_id, exc)
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("summary_version")
            not in {_SUMMARY_VERSION, _PREVIOUS_SUMMARY_VERSION}
            or not isinstance(metadata.get("document"), str)
            or not isinstance(metadata.get("models"), list)
            or not all(isinstance(model, str) for model in metadata["models"])
        ):
            continue
        try:
            answer = _read_saved_summary_text(summary_id, metadata, summary_path)
        except OSError as exc:
            logger.exception("Could not normalize saved LMI summary %s", summary_id)
            raise HTTPException(
                status_code=500,
                detail="Could not update a saved summary file to plain text.",
            ) from exc
        if not answer.strip():
            continue
        created_at = metadata.get("created_at", "")
        if not isinstance(created_at, str):
            continue
        summaries.append(
            {
                "summary_id": summary_id,
                "document": metadata["document"],
                "models": metadata["models"],
                "created_at": created_at,
            }
        )
    return sorted(
        summaries,
        key=lambda summary: str(summary["created_at"]),
        reverse=True,
    )


def _split_summary_text(text: str, max_chars: int = _SUMMARY_CHUNK_CHARS) -> list[str]:
    """Split report text into bounded, contiguous chunks without dropping characters."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + max_chars // 2, end)
            if boundary < 0:
                boundary = text.rfind(" ", start + max_chars // 2, end)
            if boundary >= start:
                end = boundary + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _ocr_pdf(path: Path) -> str:
    """Render a scanned PDF locally and extract text with the Tesseract executable."""
    if not shutil.which("tesseract"):
        raise HTTPException(
            status_code=503,
            detail="Scanned PDF OCR requires Tesseract OCR to be installed on the server.",
        )
    if path.stat().st_size > _OCR_MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The selected PDF is too large for scanned-document OCR.",
        )

    try:
        document = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        logger.warning("PDFium could not open selected report %s", path.name)
        raise HTTPException(
            status_code=422,
            detail="The selected PDF could not be opened for OCR.",
        ) from exc

    page_count = len(document)
    if page_count > _OCR_MAX_PAGES:
        document.close()
        raise HTTPException(
            status_code=413,
            detail=f"Scanned-PDF OCR is limited to {_OCR_MAX_PAGES} pages.",
        )

    recognized_pages: list[str] = []
    try:
        for page_number in range(page_count):
            page = document[page_number]
            width, height = page.get_size()
            if width * height * _OCR_RENDER_SCALE**2 > _OCR_MAX_PIXELS_PER_PAGE:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF page {page_number + 1} is too large for OCR.",
                )

            try:
                image = page.render(scale=_OCR_RENDER_SCALE).to_pil()
                with io.BytesIO() as image_stream:
                    image.save(image_stream, format="PNG")
                    image_bytes = image_stream.getvalue()
                image.close()
            except pdfium.PdfiumError as exc:
                logger.warning(
                    "PDFium could not render %s page %d",
                    path.name,
                    page_number + 1,
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"PDF page {page_number + 1} could not be rendered for OCR.",
                ) from exc

            try:
                result = subprocess.run(
                    ["tesseract", "stdin", "stdout"],
                    input=image_bytes,
                    capture_output=True,
                    timeout=_OCR_PAGE_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=504,
                    detail=f"OCR timed out on PDF page {page_number + 1}.",
                ) from exc
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Tesseract OCR is not available on the server.",
                ) from exc

            if result.returncode:
                logger.warning(
                    "Tesseract failed for %s page %d with exit status %d",
                    path.name,
                    page_number + 1,
                    result.returncode,
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"OCR failed on PDF page {page_number + 1}.",
                )
            recognized_pages.append(result.stdout.decode("utf-8", errors="replace"))
    finally:
        document.close()

    return "\n".join(recognized_pages)


async def _request_model_text(
    client: AsyncOpenAI,
    model_id: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, str]:
    """Return completion text and the model ID OpenRouter reports as used."""
    completion = await client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        extra_body={
            "reasoning": {
                "effort": "low",
                "exclude": True,
            }
        },
    )
    choice = completion.choices[0] if completion.choices else None
    message = choice.message if choice else None
    answer = message.content if message else None
    finish_reason = getattr(choice, "finish_reason", None) if choice else "no_choices"
    if not answer or not answer.strip():
        if finish_reason == "length":
            retry_tokens = min(max_tokens * 4, _MAX_LMI_RETRY_TOKENS)
            logger.info(
                "Retrying empty, token-limited OpenRouter response with reasoning disabled: "
                "requested_model=%s actual_model=%s retry_max_tokens=%d",
                model_id,
                completion.model,
                retry_tokens,
            )
            retry_options: dict[str, object] = {
                "reasoning": {
                    "effort": "none",
                    "exclude": True,
                }
            }
            if model_id == _DEFAULT_MODEL_ID:
                retry_options["plugins"] = [
                    {
                        "id": "auto-router",
                        "cost_tier": "low",
                    }
                ]
            completion = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=retry_tokens,
                extra_body=retry_options,
            )
            choice = completion.choices[0] if completion.choices else None
            message = choice.message if choice else None
            answer = message.content if message else None
            finish_reason = (
                getattr(choice, "finish_reason", None) if choice else "no_choices"
            )

    if not answer or not answer.strip():
        reasoning_present = bool(getattr(message, "reasoning", None))
        logger.warning(
            "OpenRouter returned no answer text: requested_model=%s actual_model=%s "
            "finish_reason=%s reasoning_present=%s",
            model_id,
            completion.model,
            finish_reason,
            reasoning_present,
        )
        if finish_reason == "length":
            selected_model = completion.model or model_id
            retry_routing = (
                " and OpenRouter Auto's low-cost routing tier"
                if model_id == _DEFAULT_MODEL_ID
                else ""
            )
            detail = (
                f"OpenRouter model {selected_model} used its output-token limit "
                "without returning summary text, even after retrying with reasoning "
                f"disabled, a larger token budget{retry_routing}. "
                "Choose a different model and try again."
            )
        else:
            detail = (
                "The selected model returned no text. Try again or choose a different model."
            )
        raise HTTPException(
            status_code=502,
            detail=detail,
            headers={"X-OpenRouter-Model": completion.model or model_id},
        )
    if not completion.model:
        raise HTTPException(
            status_code=502,
            detail="OpenRouter did not identify the model used for this response.",
        )
    return answer, completion.model


@router.get(
    "/openrouter",
    response_class=HTMLResponse,
    summary="OpenRouter Model Playground",
    description=(
        "Maintenance page for testing text prompts and summarizing local LMI "
        "reports with the configured OpenRouter model. No MySQL data is queried."
    ),
)
async def openrouter_page(request: Request) -> HTMLResponse:
    """Render the OpenRouter model playground."""
    return templates.TemplateResponse(
        request,
        "maintenance/openrouter.html",
        {
            "active_page": "openrouter",
            "model_id": _get_model_id(),
            "lmi_documents": _list_lmi_documents(),
            "saved_summaries": _list_saved_summaries(),
        },
    )


@router.get(
    "/api/openrouter/lmi-summaries/{summary_id}/download",
    response_class=FileResponse,
    summary="Download a saved LMI summary",
    description="Downloads one previously generated LMI summary as a plain-text file.",
)
async def download_lmi_summary(summary_id: str) -> FileResponse:
    """Return one validated, locally saved LMI summary text file."""
    summary_path, metadata_path = _get_summary_paths(summary_id)
    summary_dir = _LMI_DIR / ".summaries"
    if (
        summary_dir.is_symlink()
        or not summary_path.is_file()
        or summary_path.is_symlink()
        or not metadata_path.is_file()
        or metadata_path.is_symlink()
        or summary_path.resolve().parent != summary_dir.resolve()
    ):
        raise HTTPException(status_code=404, detail="Saved summary not found.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read LMI summary metadata %s: %s", summary_id, exc)
        raise HTTPException(status_code=404, detail="Saved summary not found.") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("summary_version")
        not in {_SUMMARY_VERSION, _PREVIOUS_SUMMARY_VERSION}
    ):
        raise HTTPException(status_code=404, detail="Saved summary not found.")
    document = metadata.get("document")
    if not isinstance(document, str) or not document:
        raise HTTPException(status_code=404, detail="Saved summary not found.")
    answer = _read_saved_summary_text(summary_id, metadata, summary_path)
    if not answer.strip():
        raise HTTPException(status_code=404, detail="Saved summary not found.")
    download_name = f"{Path(document).stem}-summary.txt"
    return FileResponse(
        summary_path,
        media_type="text/plain",
        filename=download_name,
    )


@router.post(
    "/api/openrouter/chat",
    response_model=OpenRouterChatResponse,
    summary="Send a prompt to the OpenRouter model",
    description=(
        "Sends one text prompt to the configured OpenRouter model and returns "
        "its text response. No database queries or document uploads are performed."
    ),
)
async def openrouter_chat(body: OpenRouterChatRequest) -> OpenRouterChatResponse:
    """Send a bounded user prompt to OpenRouter and return the model response."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt must not be blank.")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be no more than {_MAX_PROMPT_CHARS} characters.",
        )

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Set OPENROUTER_API_KEY in the project-root .env file.",
        )

    model_id = _get_model_id()
    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=90.0,
        ) as client:
            completion = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_COMPLETION_TOKENS,
            )
    except OpenAIError as exc:
        logger.exception("OpenRouter request failed for model %s", model_id)
        raise HTTPException(
            status_code=502,
            detail="OpenRouter request failed. Check the API key, model ID, and provider status.",
        ) from exc

    if not completion.choices or not completion.choices[0].message.content:
        logger.warning("OpenRouter returned no text for model %s", model_id)
        raise HTTPException(
            status_code=502,
            detail="The selected model returned no text response.",
        )
    if not completion.model:
        raise HTTPException(
            status_code=502,
            detail="OpenRouter did not identify the model used for this response.",
        )

    return OpenRouterChatResponse(
        model=completion.model,
        answer=completion.choices[0].message.content,
    )


@router.post(
    "/api/openrouter/lmi-summary",
    response_model=OpenRouterLmiSummaryResponse,
    summary="Summarize a selected LMI report with OpenRouter",
    description=(
        "Accepts a supported filename from raw_data/lmi, extracts its text, "
        "summarizes the extracted text in bounded chunks, and sends only that "
        "selected report to the configured OpenRouter model. Saves the result "
        "as a local text file and reuses it while the source file is unchanged."
    ),
)
async def openrouter_lmi_summary(
    body: OpenRouterLmiSummaryRequest,
) -> OpenRouterLmiSummaryResponse:
    """Summarize one selected LMI report using the configured OpenRouter model."""
    source_path = _resolve_lmi_document(body.filename)
    cached_summary = _read_cached_lmi_summary(body.filename, source_path)
    if cached_summary is not None:
        return OpenRouterLmiSummaryResponse(
            models=cached_summary["models"],
            document=body.filename,
            answer=cached_summary["answer"],
            summary_id=cached_summary["summary_id"],
            cached=True,
        )

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Set OPENROUTER_API_KEY in the project-root .env file.",
        )

    document_text = _read_lmi_document(source_path)
    model_id = _get_model_id()
    chunks = _split_summary_text(document_text)
    model_ids: list[str] = []

    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=90.0,
        ) as client:
            if len(chunks) == 1:
                prompt = (
                    "Summarize the supplied Logistics Managers Index (LMI) report. "
                    "Use only facts present in the text, preserve exact dates and "
                    "metric values, and cite the source filename for key findings. "
                    "Do not invent missing values. Organize the answer as a short "
                    "executive summary followed by concise bullets for important "
                    "trends, logistics signals, and caveats.\n\n"
                    f"Source file: {body.filename}\n"
                    "--- REPORT TEXT START ---\n"
                    f"{chunks[0]}\n"
                    "--- REPORT TEXT END ---"
                )
                answer, model_used = await _request_model_text(
                    client,
                    model_id,
                    prompt,
                    _MAX_LMI_SUMMARY_TOKENS,
                )
                model_ids.append(model_used)
            else:
                chunk_summaries: list[str] = []
                for index, chunk in enumerate(chunks, start=1):
                    prompt = (
                        "Summarize only the facts and metric values in this portion "
                        "of an LMI report. Preserve exact dates and numbers, do not "
                        "infer conclusions about portions not shown, and keep the "
                        "notes concise for a final report synthesis.\n\n"
                        f"Source file: {body.filename}\n"
                        f"Report portion {index} of {len(chunks)}\n"
                        "--- REPORT TEXT START ---\n"
                        f"{chunk}\n"
                        "--- REPORT TEXT END ---"
                    )
                    chunk_summary, model_used = await _request_model_text(
                        client,
                        model_id,
                        prompt,
                        _MAX_LMI_CHUNK_SUMMARY_TOKENS,
                    )
                    chunk_summaries.append(chunk_summary)
                    model_ids.append(model_used)

                while len(chunk_summaries) > _SUMMARY_REDUCTION_GROUP_SIZE:
                    reduced_summaries: list[str] = []
                    for start in range(
                        0,
                        len(chunk_summaries),
                        _SUMMARY_REDUCTION_GROUP_SIZE,
                    ):
                        group = chunk_summaries[
                            start : start + _SUMMARY_REDUCTION_GROUP_SIZE
                        ]
                        reduction_prompt = (
                            "Concisely combine these notes from portions of the same "
                            "Logistics Managers Index (LMI) report. Preserve key dates "
                            "and metric values, do not add facts, and retain important "
                            "caveats.\n\n"
                            f"Source file: {body.filename}\n"
                            + "\n\n".join(
                                f"--- NOTES {index} ---\n{summary}"
                                for index, summary in enumerate(group, start=1)
                            )
                        )
                        reduced, model_used = await _request_model_text(
                            client,
                            model_id,
                            reduction_prompt,
                            _MAX_LMI_CHUNK_SUMMARY_TOKENS,
                        )
                        reduced_summaries.append(reduced)
                        model_ids.append(model_used)
                    chunk_summaries = reduced_summaries

                synthesis_prompt = (
                    "Synthesize these notes from every portion of one Logistics "
                    "Managers Index (LMI) report into a concise, accurate summary. "
                    "Use only the supplied notes, preserve exact dates and metric "
                    "values, and do not invent missing information. Organize the "
                    "answer as a short executive summary followed by concise bullets "
                    "for important trends, logistics signals, and caveats. Cite the "
                    f"source filename ({body.filename}) for key findings.\n\n"
                    + "\n\n".join(
                        f"--- PORTION {index} SUMMARY ---\n{summary}"
                        for index, summary in enumerate(chunk_summaries, start=1)
                    )
                )
                answer, model_used = await _request_model_text(
                    client,
                    model_id,
                    synthesis_prompt,
                    _MAX_LMI_SUMMARY_TOKENS,
                )
                model_ids.append(model_used)
    except OpenAIError as exc:
        logger.exception(
            "OpenRouter LMI summary failed for %s using model %s",
            body.filename,
            model_id,
        )
        raise HTTPException(
            status_code=502,
            detail="OpenRouter could not summarize the selected LMI report. Check the API key, model ID, and provider status.",
        ) from exc

    answer = _markdown_to_plain_text(answer)
    if not answer:
        raise HTTPException(
            status_code=502,
            detail="The selected model returned no readable summary text.",
        )

    summary_id = None
    cache_warning = None
    try:
        summary_id = _save_lmi_summary(
            body.filename,
            source_path,
            list(dict.fromkeys(model_ids)),
            answer,
        )
    except OSError:
        logger.exception("Could not save LMI summary for %s", body.filename)
        cache_warning = "Summary was generated but could not be saved to the local summary folder."

    return OpenRouterLmiSummaryResponse(
        models=list(dict.fromkeys(model_ids)),
        document=body.filename,
        answer=answer,
        summary_id=summary_id,
        cache_warning=cache_warning,
    )
