"""
OCR processing functionality using OnnxTR + PyMuPDF.

Upload PDF(s), run OCR with deep-learning models, return searchable PDF.
No system binaries required (no Tesseract, Ghostscript, etc.).
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageOps

from .ocr_engine import (
    OCR_AVAILABLE,
    OCR_DPI,
    get_predictor,
    pdf_page_to_numpy,
    ocr_pages_words,
)
from .utils import _is_mac_resource_junk

logger = logging.getLogger(__name__)

# Image extensions supported by the /ocr endpoint
OCR_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _insert_ocr_text_layer(page: "fitz.Page", words: list, img_rect=None) -> None:
    """Insert invisible OCR text onto a fitz page."""
    if not words:
        return
    rect = img_rect or page.rect
    pw = rect.width
    ph = rect.height
    ox, oy = rect.x0, rect.y0
    for w in words:
        x0, y0 = ox + w.xmin * pw, oy + w.ymin * ph
        x1, y1 = ox + w.xmax * pw, oy + w.ymax * ph
        target_w = x1 - x0
        target_h = y1 - y0
        if target_w <= 0 or target_h <= 0 or not w.text:
            continue
        # Font size based on height — keeps line heights consistent
        fontsize = max(1.0, target_h * 0.8)
        # Append a trailing space so PyMuPDF's text extractor preserves
        # word boundaries. Without it, OnnxTR's tight word boxes cause
        # adjacent words to merge on extraction (e.g. "PlaintiffAcme").
        text = w.text + " "
        # Horizontal scale to match bounding box width
        text_w = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        h_scale = (target_w / text_w) if text_w > 0 else 1.0
        morph = (fitz.Point(x0, y1), fitz.Matrix(h_scale, 1.0))
        page.insert_text(
            fitz.Point(x0, y1), text,
            fontname="helv", fontsize=fontsize,
            render_mode=3, morph=morph,
        )


def ocr_pdf_bytes(pdf_bytes: bytes, dpi: int = OCR_DPI) -> bytes:
    """
    Perform OCR on PDF bytes and return searchable PDF bytes.

    Pages that already contain extractable text are left untouched.
    Text-less pages are rendered to images, run through OnnxTR, and an
    invisible text layer is inserted so the PDF becomes searchable.

    Pages are processed one at a time to keep memory usage low.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    ocr_needed = False
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        existing_text = (page.get_text("text") or "").strip()
        if not existing_text:
            ocr_needed = True
            break

    if not ocr_needed:
        out = doc.tobytes()
        doc.close()
        return out

    # Process one page at a time to minimise memory usage
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        existing_text = (page.get_text("text") or "").strip()
        if existing_text:
            continue  # already has text — skip

        page_img = pdf_page_to_numpy(page, dpi=dpi)
        words_list = ocr_pages_words([page_img])
        del page_img

        if words_list and words_list[0]:
            _insert_ocr_text_layer(page, words_list[0])

    out = doc.tobytes()
    doc.close()
    return out


def ocr_image_bytes(img_bytes: bytes, dpi: int = OCR_DPI) -> bytes:
    """
    OCR a single-frame image (JPG, PNG) and return a searchable PDF.

    The image is embedded into a PDF page at its native resolution, then an
    invisible OCR text layer is placed on top.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    # Open, fix orientation, ensure RGB
    im = Image.open(io.BytesIO(img_bytes))
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        im = im.convert("RGB")

    # Page dimensions in points (1 inch = 72 pt)
    width_pt = im.width * 72.0 / dpi
    height_pt = im.height * 72.0 / dpi

    # Define the target PDF size
    letter_w = 612.0
    letter_h = 792.0

    # Fit image inside the letter page
    scale = min(letter_w / width_pt, letter_h / height_pt, 1.0)

    # Re-encode to JPEG (EXIF transpose may have rotated)
    jpeg_buf = io.BytesIO()
    im.save(jpeg_buf, format="JPEG", quality=85)
    jpeg_bytes = jpeg_buf.getvalue()

    # Convert to numpy for OCR, then release PIL image
    page_img = np.array(im)
    del im

    # Build PDF page with the image
    doc = fitz.open()
    page = doc.new_page(width=letter_w, height=letter_h)
    scaled_w = width_pt * scale
    scaled_h = height_pt * scale
    x_offset = (letter_w - scaled_w) / 2
    y_offset = (letter_h - scaled_h) / 2
    img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_w, y_offset + scaled_h)
    page.insert_image(img_rect, stream=jpeg_bytes)
    del jpeg_bytes

    # Run OCR and insert text layer
    words_list = ocr_pages_words([page_img])
    del page_img

    if words_list and words_list[0]:
        _insert_ocr_text_layer(page, words_list[0], img_rect)

    out = doc.tobytes()
    doc.close()
    return out


def ocr_tiff_bytes(img_bytes: bytes, dpi: int = OCR_DPI) -> bytes:
    """
    OCR a TIFF image (single or multi-page) and return a searchable PDF.

    Each TIFF frame becomes one PDF page with the image embedded and an
    invisible OCR text layer on top.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    im = Image.open(io.BytesIO(img_bytes))

    # Single-frame TIFF — delegate to the simpler path
    if getattr(im, "n_frames", 1) == 1:
        im.close()
        return ocr_image_bytes(img_bytes, dpi=dpi)

    # Multi-frame TIFF
    doc = fitz.open()
    n_frames = im.n_frames

    for frame_idx in range(n_frames):
        im.seek(frame_idx)
        frame = im.copy()
        frame = ImageOps.exif_transpose(frame)
        if frame.mode != "RGB":
            frame = frame.convert("RGB")

        width_pt = frame.width * 72.0 / dpi
        height_pt = frame.height * 72.0 / dpi

        # Define the target PDF size
        letter_w = 612.0
        letter_h = 792.0

        # Fit image inside the letter page
        scale = min(letter_w / width_pt, letter_h / height_pt, 1.0)

        # Re-encode frame to JPEG
        jpeg_buf = io.BytesIO()
        frame.save(jpeg_buf, format="JPEG", quality=85)
        jpeg_bytes = jpeg_buf.getvalue()

        # Convert to numpy for OCR
        frame_np = np.array(frame)
        del frame

        # Add page with embedded image
        page = doc.new_page(width=letter_w, height=letter_h)
        scaled_w = width_pt * scale
        scaled_h = height_pt * scale
        x_offset = (letter_w - scaled_w) / 2
        y_offset = (letter_h - scaled_h) / 2
        img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_w, y_offset + scaled_h)
        page.insert_image(img_rect, stream=jpeg_bytes)
        del jpeg_bytes

        # Run OCR and insert text layer
        words_list = ocr_pages_words([frame_np])
        del frame_np

        if words_list and words_list[0]:
            _insert_ocr_text_layer(page, words_list[0], img_rect)

    del im

    out = doc.tobytes()
    doc.close()
    return out


def process_ocr_zip_bytes(zip_bytes: bytes) -> bytes:
    """
    Process a ZIP file: OCR all PDFs within, pass non-PDFs through unchanged.

    Writes each result to the output ZIP incrementally to avoid accumulating
    all processed files in memory simultaneously.
    """
    out_buf = io.BytesIO()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin:
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.is_dir():
                    continue
                if _is_mac_resource_junk(info.filename):
                    continue

                file_data = zin.read(info)
                ext = Path(info.filename).suffix.lower()
                out_name = info.filename

                if ext == ".pdf":
                    file_data = ocr_pdf_bytes(file_data)
                elif ext in OCR_IMAGE_EXTS:
                    try:
                        if ext in (".tif", ".tiff"):
                            file_data = ocr_tiff_bytes(file_data)
                        else:
                            file_data = ocr_image_bytes(file_data)
                        out_name = str(Path(info.filename).with_suffix(".pdf"))
                    except Exception:
                        logger.warning("Failed to OCR image %s, passing through", info.filename)

                zout.writestr(out_name, file_data)
                del file_data

    return out_buf.getvalue()
