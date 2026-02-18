"""
Shared OnnxTR OCR engine wrapper.

Provides a lazy-loaded singleton predictor and helpers for converting
PDF pages / raw images to text and word-level bounding boxes.

All heavy imports (onnxtr, numpy) happen inside functions so the module
can be imported cheaply even when the dependencies are missing.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Shared DPI setting (all OCR render paths use this)
# ---------------------------------------------------------------------------
OCR_DPI = int(os.environ.get("ONNXTR_DPI", "150"))

# ---------------------------------------------------------------------------
# Availability flag
# ---------------------------------------------------------------------------
try:
    from onnxtr.models import ocr_predictor  # noqa: F401
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# ---------------------------------------------------------------------------
# OcrWord dataclass
# ---------------------------------------------------------------------------

@dataclass
class OcrWord:
    """Single recognised word with bounding box (normalised 0-1)."""
    text: str
    confidence: float
    xmin: float
    ymin: float
    xmax: float
    ymax: float

# ---------------------------------------------------------------------------
# Lazy singleton predictor
# ---------------------------------------------------------------------------
_predictor = None
_predictor_lock = threading.Lock()


def get_predictor():
    """Return a thread-safe singleton ``ocr_predictor`` instance.

    Model architectures can be overridden via env vars:
        ONNXTR_DET_ARCH   (default ``fast_tiny``)
        ONNXTR_RECO_ARCH  (default ``crnn_mobilenet_v3_small``)
    """
    global _predictor
    if _predictor is not None:
        return _predictor
    with _predictor_lock:
        if _predictor is not None:  # double-check
            return _predictor
        if not OCR_AVAILABLE:
            raise RuntimeError(
                "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
            )
        from onnxtr.models import ocr_predictor as _build

        det = os.environ.get("ONNXTR_DET_ARCH", "fast_tiny")
        reco = os.environ.get("ONNXTR_RECO_ARCH", "crnn_mobilenet_v3_small")
        _predictor = _build(det_arch=det, reco_arch=reco)
        return _predictor

# ---------------------------------------------------------------------------
# Image conversion helpers
# ---------------------------------------------------------------------------

def pdf_page_to_numpy(page, dpi: int = OCR_DPI) -> np.ndarray:
    """Render a PyMuPDF ``fitz.Page`` to an RGB numpy array at *dpi*."""
    zoom = dpi / 72.0
    mat = __import__("fitz").Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:  # RGBA → RGB
        img = img[:, :, :3]
    return img


def image_bytes_to_numpy(img_bytes: bytes) -> np.ndarray:
    """Convert raw image bytes (PNG / JPEG / …) to an RGB numpy array."""
    from PIL import Image, ImageOps
    import io

    with Image.open(io.BytesIO(img_bytes)) as im:
        im = ImageOps.exif_transpose(im)
        return np.array(im.convert("RGB"))

# ---------------------------------------------------------------------------
# OCR convenience wrappers
# ---------------------------------------------------------------------------

def ocr_single_page_text(page_img: np.ndarray) -> str:
    """Run OCR on a single page image and return plain text."""
    predictor = get_predictor()
    result = predictor([page_img])
    lines: list[str] = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                lines.append(" ".join(w.value for w in line.words))
    return "\n".join(lines)


def ocr_pages_words(pages: List[np.ndarray]) -> List[List[OcrWord]]:
    """Run OCR on multiple page images and return per-page word lists.

    Each ``OcrWord`` carries normalised bounding-box coordinates in [0, 1].
    """
    if not pages:
        return []
    predictor = get_predictor()
    result = predictor(pages)
    all_words: List[List[OcrWord]] = []
    for page in result.pages:
        page_words: List[OcrWord] = []
        for block in page.blocks:
            for line in block.lines:
                for w in line.words:
                    (xmin, ymin), (xmax, ymax) = w.geometry
                    page_words.append(
                        OcrWord(
                            text=w.value,
                            confidence=w.confidence,
                            xmin=xmin,
                            ymin=ymin,
                            xmax=xmax,
                            ymax=ymax,
                        )
                    )
        all_words.append(page_words)
    return all_words
