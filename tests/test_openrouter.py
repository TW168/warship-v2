"""Tests for the Maintenance OpenRouter playground."""

import json
from types import SimpleNamespace
import shutil

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
import pytest

from main import app
from routers.maintenance import openrouter

client = TestClient(app)


def test_openrouter_page_displays_model_and_document_options(monkeypatch, tmp_path):
    """The page shows the configured model and only supported report choices."""
    (tmp_path / "report_a.txt").write_text("Report text.", encoding="utf-8")
    (tmp_path / "notes.docx").write_bytes(b"unsupported")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setenv("OPENROUTER_MODEL_ID", "openrouter/auto")

    response = client.get("/maintenance/openrouter")

    assert response.status_code == 200
    assert "OpenRouter Auto" in response.text
    assert "openrouter/auto" in response.text
    assert "Actual model:" in response.text
    assert 'id="modelIndicator"' in response.text
    assert "Summarize selected report" in response.text
    assert "limited to 50 pages" in response.text
    assert "summarized in chunks" in response.text
    assert 'value="report_a.txt"' in response.text
    assert "notes.docx" not in response.text
    assert "/maintenance/api/openrouter/lmi-summary" in response.text


def test_openrouter_chat_requires_api_key(monkeypatch):
    """The chat endpoint reports a clear configuration error when no key exists."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = client.post(
        "/maintenance/api/openrouter/chat",
        json={"prompt": "Say hello"},
    )

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_openrouter_chat_returns_model_response(monkeypatch):
    """A valid prompt is sent to the configured model and its answer is returned."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_ID", "openrouter/auto")

    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "openrouter/auto"
            assert kwargs["messages"] == [{"role": "user", "content": "Say hello"}]
            return SimpleNamespace(
                model="x-ai/grok-4.7",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Hello!")
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-key"
            assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
            self.chat = SimpleNamespace(
                completions=FakeCompletions(),
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(openrouter, "AsyncOpenAI", FakeClient)

    response = client.post(
        "/maintenance/api/openrouter/chat",
        json={"prompt": "  Say hello  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "x-ai/grok-4.7",
        "answer": "Hello!",
    }


def test_openrouter_lmi_summary_summarizes_only_selected_report(monkeypatch, tmp_path):
    """The LMI summary sends only the selected report and identifies its source."""
    (tmp_path / "report_a.txt").write_text("First report source.", encoding="utf-8")
    (tmp_path / "report_b.txt").write_text("Second report source.", encoding="utf-8")
    (tmp_path / "notes.docx").write_bytes(b"unsupported for text extraction")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setattr(
        openrouter,
        "_extract_text",
        lambda path, max_chars=None: path.read_text(encoding="utf-8"),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_ID", "openrouter/auto")
    requests = []

    class FakeCompletions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            prompt = kwargs["messages"][0]["content"]
            assert kwargs["model"] == "openrouter/auto"
            assert kwargs["max_tokens"] == 4_096
            assert "report_a.txt" in prompt
            assert "report_b.txt" not in prompt
            assert "First report source." in prompt
            assert "Second report source." not in prompt
            return SimpleNamespace(
                model="x-ai/grok-4.7",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "# Summary\n\n"
                                "**Key point:** details.\n\n"
                                "- First item\n"
                                "- Second item"
                            )
                        )
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-key"
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(openrouter, "AsyncOpenAI", FakeClient)
    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "report_a.txt"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["models"] == ["x-ai/grok-4.7"]
    assert result["document"] == "report_a.txt"
    expected_summary = "Summary\n\nKey point: details.\n\n- First item\n- Second item"
    assert result["answer"] == expected_summary
    assert result["cached"] is False
    assert result["cache_warning"] is None
    summary_id = result["summary_id"]
    assert (tmp_path / ".summaries" / f"{summary_id}.txt").read_text(
        encoding="utf-8"
    ) == expected_summary
    assert openrouter._list_lmi_documents() == ["report_b.txt"]

    page_response = client.get("/maintenance/openrouter")
    assert 'value="report_a.txt"' not in page_response.text
    assert (
        f"/maintenance/api/openrouter/lmi-summaries/{summary_id}/download"
        in page_response.text
    )

    download_response = client.get(
        f"/maintenance/api/openrouter/lmi-summaries/{summary_id}/download"
    )
    assert download_response.status_code == 200
    assert download_response.text == expected_summary

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cached_response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "report_a.txt"},
    )
    assert cached_response.status_code == 200
    assert cached_response.json()["cached"] is True
    assert cached_response.json()["summary_id"] == summary_id
    assert cached_response.json()["answer"] == expected_summary
    assert len(requests) == 1

    (tmp_path / "report_a.txt").write_text("Updated report source.", encoding="utf-8")
    assert openrouter._list_lmi_documents() == ["report_a.txt", "report_b.txt"]


def test_openrouter_lmi_summary_reports_token_limit_without_reasoning(monkeypatch, tmp_path):
    """A reasoning-only truncated response explains the failure without leaking reasoning."""
    (tmp_path / "report.txt").write_text("Report text.", encoding="utf-8")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setattr(
        openrouter,
        "_extract_text",
        lambda path, max_chars=None: "Report text.",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    requests = []

    class FakeCompletions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                model="provider/model",
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(
                            content=None,
                            reasoning="private internal reasoning",
                        ),
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(openrouter, "AsyncOpenAI", FakeClient)
    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "report.txt"},
    )

    assert response.status_code == 502
    assert "output-token limit" in response.json()["detail"]
    assert "private internal reasoning" not in response.text
    assert response.headers["X-OpenRouter-Model"] == "provider/model"
    assert len(requests) == 2
    assert requests[0]["extra_body"]["reasoning"]["effort"] == "low"
    assert requests[1]["extra_body"]["reasoning"]["effort"] == "none"
    assert requests[1]["max_tokens"] == 8_192
    assert requests[1]["extra_body"]["plugins"] == [
        {"id": "auto-router", "cost_tier": "low"}
    ]


def test_openrouter_lmi_summary_retries_token_limited_response(monkeypatch, tmp_path):
    """A summary succeeds when the first response spends its token budget reasoning."""
    (tmp_path / "report.txt").write_text("Report text.", encoding="utf-8")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setattr(
        openrouter,
        "_extract_text",
        lambda path, max_chars=None: "Report text.",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    requests = []

    class FakeCompletions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                return SimpleNamespace(
                    model="provider/reasoning-model",
                    choices=[
                        SimpleNamespace(
                            finish_reason="length",
                            message=SimpleNamespace(
                                content=None,
                                reasoning="not returned to the user",
                            ),
                        )
                    ],
                )
            return SimpleNamespace(
                model="provider/summary-model",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="Concise report summary."),
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(openrouter, "AsyncOpenAI", FakeClient)
    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "report.txt"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["models"] == ["provider/summary-model"]
    assert result["document"] == "report.txt"
    assert result["answer"] == "Concise report summary."
    assert len(result["summary_id"]) == 64
    assert result["cached"] is False
    assert result["cache_warning"] is None
    assert len(requests) == 2
    assert requests[0]["extra_body"]["reasoning"]["effort"] == "low"
    assert requests[1]["extra_body"]["reasoning"]["effort"] == "none"
    assert requests[1]["max_tokens"] == 8_192
    assert requests[1]["extra_body"]["plugins"] == [
        {"id": "auto-router", "cost_tier": "low"}
    ]


def test_cached_markdown_summary_is_migrated_without_model_call(monkeypatch, tmp_path):
    """Old cached Markdown is converted and reused without another provider request."""
    source_path = tmp_path / "report.txt"
    source_path.write_text("Source report.", encoding="utf-8")
    summary_id, source_hash = openrouter._get_lmi_summary_id(
        source_path.name,
        source_path,
    )
    summary_dir = tmp_path / ".summaries"
    summary_dir.mkdir()
    summary_path = summary_dir / f"{summary_id}.txt"
    summary_path.write_text(
        "# Cached title\n\n**Key:** finding\n\n- One\n- Two",
        encoding="utf-8",
    )
    (summary_dir / f"{summary_id}.json").write_text(
        json.dumps(
            {
                "summary_version": openrouter._PREVIOUS_SUMMARY_VERSION,
                "document": source_path.name,
                "source_sha256": source_hash,
                "models": ["previous/model"],
                "created_at": "2026-11-16T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": source_path.name},
    )

    assert response.status_code == 200
    assert response.json()["cached"] is True
    assert response.json()["answer"] == "Cached title\n\nKey: finding\n\n- One\n- Two"
    assert summary_path.read_text(encoding="utf-8") == response.json()["answer"]
    metadata = json.loads((summary_dir / f"{summary_id}.json").read_text(encoding="utf-8"))
    assert metadata["summary_version"] == openrouter._SUMMARY_VERSION


def test_openrouter_lmi_summary_rejects_unlisted_document(monkeypatch, tmp_path):
    """The summary endpoint rejects filenames outside the LMI report folder."""
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "../secret.txt"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_summary_chunks_preserve_all_source_text():
    """Chunking keeps every character and bounds each model request."""
    source = ("LMI findings and metrics.\n" * 2_500) + "Final metric: 92.4"

    chunks = openrouter._split_summary_text(source, max_chars=2_000)

    assert len(chunks) > 1
    assert "".join(chunks) == source
    assert all(len(chunk) <= 2_000 for chunk in chunks)


def test_lmi_text_extraction_can_bypass_existing_character_limit(tmp_path):
    """Selected-report extraction reads the full file while default callers stay bounded."""
    source = "LMI metric and trend.\n" * 1_000
    path = tmp_path / "long.txt"
    path.write_text(source, encoding="utf-8")

    assert len(openrouter._extract_text(path)) == 12_000
    assert openrouter._extract_text(path, max_chars=None) == source


def test_openrouter_lmi_summary_uses_chunks_and_reports_all_models(
    monkeypatch, tmp_path
):
    """Long reports are summarized in chunks then synthesized with all model IDs."""
    source = ("A" * 24_000) + "\n" + ("B" * 24_000)
    (tmp_path / "long.txt").write_text(source, encoding="utf-8")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)
    monkeypatch.setattr(
        openrouter,
        "_extract_text",
        lambda path, max_chars=None: path.read_text(encoding="utf-8"),
    )
    monkeypatch.setattr(openrouter, "_SUMMARY_REDUCTION_GROUP_SIZE", 2)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    prompts = []

    class FakeCompletions:
        async def create(self, **kwargs):
            prompts.append(kwargs["messages"][0]["content"])
            request_index = len(prompts)
            return SimpleNamespace(
                model=f"provider/model-{request_index}",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=f"Summary {request_index}.")
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(openrouter, "AsyncOpenAI", FakeClient)
    response = client.post(
        "/maintenance/api/openrouter/lmi-summary",
        json={"filename": "long.txt"},
    )

    assert response.status_code == 200
    result = response.json()
    assert len(prompts) == 6
    assert "Report portion 1 of 3" in prompts[0]
    assert "Report portion 2 of 3" in prompts[1]
    assert "Report portion 3 of 3" in prompts[2]
    assert "Concisely combine these notes" in prompts[3]
    assert "Concisely combine these notes" in prompts[4]
    assert "Synthesize these notes" in prompts[5]
    source_portions = [
        prompt.split("--- REPORT TEXT START ---\n", 1)[1].split(
            "\n--- REPORT TEXT END ---", 1
        )[0]
        for prompt in prompts[:3]
    ]
    assert "".join(source_portions) == source
    assert result["models"] == [
        "provider/model-1",
        "provider/model-2",
        "provider/model-3",
        "provider/model-4",
        "provider/model-5",
        "provider/model-6",
    ]
    assert result["answer"] == "Summary 6."


def test_scanned_pdf_ocr_rejects_more_than_50_pages(monkeypatch, tmp_path):
    """The scanned-PDF OCR cap rejects a document before rendering pages."""
    pdf_path = tmp_path / "too-many-pages.pdf"
    pdf_path.write_bytes(b"pdf")
    monkeypatch.setattr(openrouter.shutil, "which", lambda name: "/usr/bin/tesseract")

    class FakeDocument:
        def __init__(self, path):
            self.closed = False

        def __len__(self):
            return 51

        def close(self):
            self.closed = True

    document = FakeDocument(pdf_path)
    monkeypatch.setattr(openrouter.pdfium, "PdfDocument", lambda path: document)

    with pytest.raises(openrouter.HTTPException) as exc_info:
        openrouter._ocr_pdf(pdf_path)

    assert exc_info.value.status_code == 413
    assert "50 pages" in exc_info.value.detail
    assert document.closed


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR is not installed")
def test_scanned_pdf_uses_local_ocr_fallback(monkeypatch, tmp_path):
    """A scanned PDF with no text layer can be read locally through OCR."""
    pdf_path = tmp_path / "scanned.pdf"
    image = Image.new("RGB", (1600, 500), "white")
    ImageDraw.Draw(image).text(
        (60, 120),
        "LMI REPORT TEXT FOR OCR TEST",
        fill="black",
        font=ImageFont.load_default(size=48),
    )
    image.save(pdf_path, format="PDF")
    monkeypatch.setattr(openrouter, "_LMI_DIR", tmp_path)

    extracted_text = openrouter._read_lmi_document(pdf_path)

    assert "REPORT" in extracted_text.upper()
    assert "OCR" in extracted_text.upper()
