"""Tests for the Vision Learning image barcode module."""

from io import BytesIO

import numpy as np
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image

from main import app
from routers import vision_learning


def _code128_image(content: str) -> bytes:
    """Create a PNG test fixture containing a real Code 128 barcode."""
    barcode = zxingcpp.create_barcode(content, zxingcpp.BarcodeFormat.Code128)
    image = Image.fromarray(np.asarray(zxingcpp.write_barcode_to_image(barcode, scale=4)))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    return buffer.getvalue()


def _small_barcode_scene(content: str) -> bytes:
    """Create a scene image where a distant barcode needs an enlarged scan pass."""
    barcode = zxingcpp.create_barcode(content, zxingcpp.BarcodeFormat.Code128)
    barcode_image = Image.fromarray(np.asarray(zxingcpp.write_barcode_to_image(barcode, scale=4))).convert("RGB")
    barcode_image = barcode_image.resize((300, 85))
    scene = Image.new("RGB", (850, 400), "white")
    scene.paste(barcode_image, (450, 150))
    buffer = BytesIO()
    scene.save(buffer, format="PNG")
    barcode_image.close()
    scene.close()
    return buffer.getvalue()


def _large_barcode_scene(content: str) -> bytes:
    """Create a warehouse-sized image with a small barcode requiring localization."""
    barcode = zxingcpp.create_barcode(content, zxingcpp.BarcodeFormat.Code128)
    barcode_image = Image.fromarray(
        np.asarray(zxingcpp.write_barcode_to_image(barcode, scale=4))
    ).convert("RGB")
    barcode_image = barcode_image.resize((300, 85))
    scene = Image.new("RGB", (3000, 1600), "white")
    scene.paste(barcode_image, (1700, 900))
    buffer = BytesIO()
    scene.save(buffer, format="PNG")
    barcode_image.close()
    scene.close()
    return buffer.getvalue()


def test_vision_learning_page_and_navigation_are_available():
    """The new page is reachable and provides its image-scanning module."""
    with TestClient(app) as client:
        response = client.get("/vision-learning")

    assert response.status_code == 200
    assert "Vision Learning" in response.text
    assert "Module 1: Find a barcode in a picture" in response.text
    assert "Scan a video for barcodes" in response.text
    assert "one frame every half second" in response.text
    assert "barcodeVideo" in response.text
    assert "image/*" in response.text
    assert "/api/vision-learning/barcodes" in response.text
    assert "The app does not retain uploaded pictures" in response.text
    assert "uploads are not encrypted in transit" in response.text
    assert 'id="barcodeCropPanel"' in response.text
    assert "Select one barcode area below to try a focused scan." in response.text
    assert "id=\"scanCropButton\"" in response.text
    assert response.text.index('href="/vision-learning"') < response.text.index("About (dropdown)")
    assert 'href="/vision-learning"' in response.text


def test_barcode_endpoint_decodes_image_without_saving_upload():
    """A Code 128 image is decoded into its symbology and text value."""
    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("label.png", _code128_image("BARCODE-123"), "image/png")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "label.png"
    assert payload["barcode_count"] == 1
    barcode = payload["barcodes"][0]
    assert barcode["value"] == "BARCODE-123"
    assert barcode["symbology"] == "Code128"
    assert barcode["x"] >= 0
    assert barcode["y"] >= 0
    assert barcode["width"] > 0
    assert barcode["height"] > 0


def test_barcode_endpoint_recovers_a_small_barcode_by_upscaling():
    """A distant barcode missed at the original crop size is found on a 2x pass."""
    content = _small_barcode_scene("REGRESSION-123")
    with Image.open(BytesIO(content)) as image:
        assert zxingcpp.read_barcodes(image) == []

    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("warehouse-scene.png", content, "image/png")},
        )

    assert response.status_code == 200
    barcode = response.json()["barcodes"][0]
    assert barcode["value"] == "REGRESSION-123"
    assert barcode["symbology"] == "Code128"
    assert barcode["x"] > 0
    assert barcode["width"] > 0


def test_barcode_endpoint_automatically_finds_barcode_inside_large_scene():
    """The server searches barcode-like regions when a full-scene decode misses."""
    content = _large_barcode_scene("REGRESSION-123")
    with Image.open(BytesIO(content)) as image:
        assert zxingcpp.read_barcodes(image) == []

    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("large-scene.png", content, "image/png")},
        )

    assert response.status_code == 200
    barcode = response.json()["barcodes"][0]
    assert barcode["value"] == "REGRESSION-123"
    assert barcode["symbology"] == "Code128"
    assert barcode["x"] > 1500
    assert barcode["width"] > 0


def test_barcode_endpoint_rejects_non_image_upload():
    """The endpoint reports malformed image uploads as a client error."""
    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("not-an-image.txt", b"not an image", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is not a readable image."


def test_barcode_endpoint_rejects_upload_over_size_limit(monkeypatch):
    """Image uploads larger than the configured limit are rejected."""
    monkeypatch.setattr(vision_learning, "MAX_IMAGE_BYTES", 8)
    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("large.png", b"012345678", "image/png")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Image exceeds the 1 MB upload limit."


def test_barcode_endpoint_rejects_images_over_pixel_limit(monkeypatch):
    """Images with excessive dimensions are rejected before barcode decoding."""
    image = Image.new("RGB", (4, 4), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    monkeypatch.setattr(vision_learning, "MAX_IMAGE_PIXELS", 12)

    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("large-dimensions.png", buffer.getvalue(), "image/png")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Image dimensions are too large to scan."


def test_barcode_endpoint_returns_empty_results_for_image_without_barcode():
    """A valid picture with no barcode returns an empty result instead of an error."""
    image = Image.new("RGB", (120, 80), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()

    with TestClient(app) as client:
        response = client.post(
            "/api/vision-learning/barcodes",
            files={"file": ("blank.png", buffer.getvalue(), "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["barcode_count"] == 0
    assert response.json()["barcodes"] == []
