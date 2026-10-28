"""Vision Learning page and image barcode scanning endpoint."""

import io
import warnings

import numpy as np
import zxingcpp
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from logging_config import get_router_logger
from schemas.vision_learning import BarcodeScanResponse, DetectedBarcode

router = APIRouter(tags=["Vision Learning"])
templates = Jinja2Templates(directory="templates")
logger = get_router_logger("vision_learning")

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
MAX_UPSCALE_SOURCE_PIXELS = 4_000_000
MAX_CROP_CANDIDATES = 120
SCAN_CROP_WIDTH = 700
SCAN_CROP_HEIGHT = 350
SCAN_CROP_STRIDE = 75
SUPPORTED_IMAGE_FORMATS = {"BMP", "GIF", "JPEG", "PNG", "TIFF", "WEBP"}


def _rank_barcode_regions(image: Image.Image) -> list[tuple[int, int]]:
    """Rank overlapping image regions by barcode-like edge density."""
    scale = min(1.0, 2000 / max(image.width, image.height))
    thumbnail_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    thumbnail = image.convert("L").resize(thumbnail_size, Image.Resampling.BILINEAR)
    gray = np.asarray(thumbnail, dtype=np.int16)
    del thumbnail

    horizontal_edges = (np.abs(np.diff(gray, axis=1)) > 28).astype(np.int64)
    vertical_edges = (np.abs(np.diff(gray, axis=0)) > 28).astype(np.int64)
    edge_density = np.zeros(gray.shape, dtype=np.int64)
    edge_density[:, 1:] += horizontal_edges
    edge_density[1:, :] += vertical_edges
    integral = np.zeros((edge_density.shape[0] + 1, edge_density.shape[1] + 1), dtype=np.int64)
    integral[1:, 1:] = edge_density.cumsum(axis=0).cumsum(axis=1)
    del gray, horizontal_edges, vertical_edges, edge_density

    thumb_width, thumb_height = thumbnail_size
    window_width = min(thumb_width, max(1, round(SCAN_CROP_WIDTH * scale)))
    window_height = min(thumb_height, max(1, round(SCAN_CROP_HEIGHT * scale)))
    stride = max(1, round(SCAN_CROP_STRIDE * scale))
    x_positions = list(range(0, thumb_width - window_width + 1, stride))
    y_positions = list(range(0, thumb_height - window_height + 1, stride))
    x_positions.append(thumb_width - window_width)
    y_positions.append(thumb_height - window_height)

    ranked: list[tuple[int, int, int]] = []
    for y in set(y_positions):
        bottom = y + window_height
        for x in set(x_positions):
            right = x + window_width
            score = (
                integral[bottom, right]
                - integral[y, right]
                - integral[bottom, x]
                + integral[y, x]
            )
            ranked.append((int(score), x, y))
    ranked.sort(reverse=True)

    regions: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for _, x, y in ranked:
        original_x = min(image.width - SCAN_CROP_WIDTH, round(x / scale))
        original_y = min(image.height - SCAN_CROP_HEIGHT, round(y / scale))
        origin = (max(0, original_x), max(0, original_y))
        if origin in seen:
            continue
        seen.add(origin)
        regions.append(origin)
        if len(regions) >= MAX_CROP_CANDIDATES:
            break
    return regions


def _scan_ranked_regions(
    image: Image.Image,
) -> list[tuple[zxingcpp.Barcode, float, int, int]]:
    """Decode barcodes and retain each enlarged crop's source-image transform."""
    found: dict[tuple[str, str], tuple[zxingcpp.Barcode, float, int, int]] = {}
    crop_width = min(SCAN_CROP_WIDTH, image.width)
    crop_height = min(SCAN_CROP_HEIGHT, image.height)
    for x, y in _rank_barcode_regions(image):
        right = min(image.width, x + crop_width)
        bottom = min(image.height, y + crop_height)
        crop = image.crop((x, y, right, bottom))
        enlarged = crop.resize(
            (crop.width * 2, crop.height * 2),
            resample=Image.Resampling.BICUBIC,
        )
        crop.close()
        try:
            for barcode in zxingcpp.read_barcodes(enlarged):
                if barcode.text:
                    found[(barcode.format.name, barcode.text)] = (barcode, 0.5, x, y)
        finally:
            enlarged.close()
    return list(found.values())


def _barcode_result(
    barcode: zxingcpp.Barcode,
    image_width: int,
    image_height: int,
    scale: float,
    offset_x: int = 0,
    offset_y: int = 0,
) -> DetectedBarcode:
    """Convert decoder coordinates to a bounded box in the uploaded image."""
    points = (
        barcode.position.top_left,
        barcode.position.top_right,
        barcode.position.bottom_left,
        barcode.position.bottom_right,
    )
    left = max(0.0, min(image_width, min(point.x for point in points) * scale + offset_x))
    top = max(0.0, min(image_height, min(point.y for point in points) * scale + offset_y))
    right = max(0.0, min(image_width, max(point.x for point in points) * scale + offset_x))
    bottom = max(0.0, min(image_height, max(point.y for point in points) * scale + offset_y))
    return DetectedBarcode(
        value=barcode.text,
        symbology=barcode.format.name,
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
    )


def _decode_image_barcodes(content: bytes) -> list[DetectedBarcode]:
    """Decode all barcodes found in one validated image held in memory."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in SUPPORTED_IMAGE_FORMATS:
                    raise HTTPException(
                        status_code=415,
                        detail="Unsupported image format. Use JPEG, PNG, WebP, BMP, TIFF, or GIF.",
                    )
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=413,
                        detail="Image dimensions are too large to scan.",
                    )
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.load()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=413,
            detail="Image dimensions are too large to scan.",
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a readable image.",
        ) from exc

    try:
        decoded = [(barcode, 1.0, 0, 0) for barcode in zxingcpp.read_barcodes(image)]
        if not decoded and image.width * image.height <= MAX_UPSCALE_SOURCE_PIXELS:
            enlarged = image.resize(
                (image.width * 2, image.height * 2),
                resample=Image.Resampling.BICUBIC,
            )
            try:
                decoded = [
                    (barcode, 0.5, 0, 0)
                    for barcode in zxingcpp.read_barcodes(enlarged)
                ]
            finally:
                enlarged.close()
        if not decoded:
            decoded = _scan_ranked_regions(image)
    except (RuntimeError, ValueError) as exc:
        logger.exception("Barcode decoder failed while scanning an uploaded image")
        raise HTTPException(
            status_code=500,
            detail="The barcode scanner could not process this image.",
        ) from exc
    finally:
        image.close()

    unique: dict[tuple[str, str], DetectedBarcode] = {}
    for barcode, scale, offset_x, offset_y in decoded:
        key = (barcode.format.name, barcode.text)
        unique[key] = _barcode_result(
            barcode,
            image.width,
            image.height,
            scale,
            offset_x,
            offset_y,
        )
    return list(unique.values())


@router.get(
    "/vision-learning",
    response_class=HTMLResponse,
    summary="Vision Learning page",
    description="Open the workspace for scanning barcodes in images or sampled video frames.",
)
async def vision_learning_page(request: Request) -> HTMLResponse:
    """Render the Vision Learning workspace."""
    return templates.TemplateResponse(
        "vision_learning/index.html",
        {"request": request, "active_page": "vision_learning"},
    )


@router.post(
    "/api/vision-learning/barcodes",
    response_model=BarcodeScanResponse,
    summary="Find barcodes in an uploaded image",
    description=(
        "Scans one uploaded image for supported barcode formats and returns "
        "each barcode's value, symbology, and image-pixel bounding box. The image "
        "is processed for this request and is not retained in application storage."
    ),
)
async def scan_image_barcodes(
    file: UploadFile = File(..., description="Image file to scan for barcodes"),
) -> BarcodeScanResponse:
    """Decode barcodes in a bounded image upload without persisting the image."""
    try:
        content = await file.read(MAX_IMAGE_BYTES + 1)
    finally:
        await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="Select an image to scan.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Image exceeds the "
                f"{max(1, MAX_IMAGE_BYTES // (1024 * 1024))} MB upload limit."
            ),
        )

    barcodes = await run_in_threadpool(_decode_image_barcodes, content)
    return BarcodeScanResponse(
        filename=file.filename or "uploaded image",
        barcode_count=len(barcodes),
        barcodes=barcodes,
    )
