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

from .ocr_engine import (
    OCR_AVAILABLE,
    OCR_DPI,
    get_predictor,
    pdf_page_to_numpy,
    ocr_pages_words,
)
from .utils import _is_mac_resource_junk


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

        if not words_list or not words_list[0]:
            continue

        pw = page.rect.width
        ph = page.rect.height
        for w in words_list[0]:
            x0 = w.xmin * pw
            y0 = w.ymin * ph
            x1 = w.xmax * pw
            y1 = w.ymax * ph
            rect = fitz.Rect(x0, y0, x1, y1)
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
