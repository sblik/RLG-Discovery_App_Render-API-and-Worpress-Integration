"""
OCR processing functionality using OnnxTR + PyMuPDF.

Upload PDF(s), run OCR with deep-learning models, return searchable PDF.
No system binaries required (no Tesseract, Ghostscript, etc.).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import fitz  # PyMuPDF

from .ocr_engine import (
    OCR_AVAILABLE,
    get_predictor,
    pdf_page_to_numpy,
    ocr_pages_words,
)
from .utils import _is_mac_resource_junk


def ocr_pdf_bytes(pdf_bytes: bytes) -> bytes:
    """
    Perform OCR on PDF bytes and return searchable PDF bytes.

    Pages that already contain extractable text are left untouched.
    Text-less pages are rendered to images, run through OnnxTR, and an
    invisible text layer is inserted so the PDF becomes searchable.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Collect pages that need OCR and their images
    pages_to_ocr: list[tuple[int, "fitz.Page"]] = []
    page_images = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        existing_text = (page.get_text("text") or "").strip()
        if existing_text:
            continue  # already has text — skip
        pages_to_ocr.append((page_index, page))
        page_images.append(pdf_page_to_numpy(page, dpi=300))

    if not pages_to_ocr:
        # All pages already had text
        out = doc.tobytes()
        doc.close()
        return out

    # Batch OCR all text-less pages
    all_words = ocr_pages_words(page_images)

    for (page_index, page), words in zip(pages_to_ocr, all_words):
        pw = page.rect.width
        ph = page.rect.height
        for w in words:
            # Convert normalised [0,1] coords to PDF points
            x0 = w.xmin * pw
            y0 = w.ymin * ph
            x1 = w.xmax * pw
            y1 = w.ymax * ph
            rect = fitz.Rect(x0, y0, x1, y1)
            # Insert invisible text (render_mode=3 = invisible fill + stroke)
            fontsize = max(1.0, (y1 - y0) * 0.8)
            page.insert_textbox(
                rect,
                w.text,
                fontsize=fontsize,
                render_mode=3,
            )

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

            if Path(info.filename).suffix.lower() == ".pdf":
                file_data = ocr_pdf_bytes(file_data)

            processed_files.append((info.filename, file_data))

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for arcname, data in processed_files:
            zout.writestr(arcname, data)

    return out_buf.getvalue()
