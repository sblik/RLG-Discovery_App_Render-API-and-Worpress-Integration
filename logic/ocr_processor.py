"""
OCR processing functionality using OnnxTR + PyMuPDF.

Upload PDF(s), run OCR with deep-learning models, return searchable PDF.
No system binaries required (no Tesseract, Ghostscript, etc.).
"""
from __future__ import annotations

import gc
import io
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

# Image extensions supported by the /ocr endpoint
OCR_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _insert_ocr_text_layer(page: "fitz.Page", words: list) -> None:
    """Insert invisible OCR text onto a fitz page."""
    if not words:
        return
    pw = page.rect.width
    ph = page.rect.height
    for w in words:
        x0, y0 = w.xmin * pw, w.ymin * ph
        x1, y1 = w.xmax * pw, w.ymax * ph
        fontsize = max(1.0, (y1 - y0) * 0.8)
        page.insert_text(fitz.Point(x0, y1), w.text, fontsize=fontsize, render_mode=3)


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
        del page_img  # free image memory immediately
        gc.collect()

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

    # Re-encode to JPEG (EXIF transpose may have rotated)
    jpeg_buf = io.BytesIO()
    im.save(jpeg_buf, format="JPEG", quality=85)
    jpeg_bytes = jpeg_buf.getvalue()

    # Convert to numpy for OCR, then release PIL image
    page_img = np.array(im)
    del im
    gc.collect()

    # Build PDF page with the image
    doc = fitz.open()
    page = doc.new_page(width=width_pt, height=height_pt)
    page.insert_image(page.rect, stream=jpeg_bytes)
    del jpeg_bytes
    gc.collect()

    # Run OCR and insert text layer
    words_list = ocr_pages_words([page_img])
    del page_img
    gc.collect()

    if words_list and words_list[0]:
        _insert_ocr_text_layer(page, words_list[0])

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

        # Re-encode frame to JPEG
        jpeg_buf = io.BytesIO()
        frame.save(jpeg_buf, format="JPEG", quality=85)
        jpeg_bytes = jpeg_buf.getvalue()

        # Convert to numpy for OCR
        frame_np = np.array(frame)
        del frame
        gc.collect()

        # Add page with embedded image
        page = doc.new_page(width=width_pt, height=height_pt)
        page.insert_image(page.rect, stream=jpeg_bytes)
        del jpeg_bytes
        gc.collect()

        # Run OCR and insert text layer
        words_list = ocr_pages_words([frame_np])
        del frame_np
        gc.collect()

        if words_list and words_list[0]:
            _insert_ocr_text_layer(page, words_list[0])

    del im
    gc.collect()

    out = doc.tobytes()
    doc.close()
    return out


def process_ocr_zip_bytes(zip_bytes: bytes) -> bytes:
    """
    Process a ZIP file: OCR all PDFs within, pass non-PDFs through unchanged.

    Returns output ZIP bytes.
    """
    processed_files: list[tuple[str, bytes]] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin:
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
                    pass  # corrupt image — pass through unchanged

            processed_files.append((out_name, file_data))

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for arcname, data in processed_files:
            zout.writestr(arcname, data)

    return out_buf.getvalue()
