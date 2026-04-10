"""
Text extraction utilities for PDFs and images.

Contains: OCR and text extraction functions used by multiple modules.
Uses PyMuPDF for native text extraction and OnnxTR as OCR fallback.
"""
from __future__ import annotations

import io
from PIL import Image, ImageOps

from PyPDF2 import PdfReader

# Optional: PyMuPDF
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

# Optional: OnnxTR OCR engine
from .ocr_engine import (
    OCR_AVAILABLE,
    OCR_DPI,
    pdf_page_to_numpy,
    image_bytes_to_numpy,
    ocr_single_page_text,
)


def _pdf_page_margin_blocks(pdf_bytes: bytes, page_index_zero: int,
                            margin_fraction: float = 0.12) -> list:
    """Return text strings from the bottom margin of a PDF page.

    Each element is the text of one positioned block, so callers can
    search blocks independently and avoid cross-block false positives.
    """
    if fitz is None:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if 0 <= page_index_zero < doc.page_count:
            page = doc.load_page(page_index_zero)
            threshold_y = page.rect.height * (1 - margin_fraction)
            blocks = page.get_text("blocks")
            result = []
            for block in blocks:
                # block: (x0, y0, x1, y1, text, block_no, block_type)
                if len(block) >= 7 and block[6] == 0 and block[1] >= threshold_y:
                    txt = str(block[4]).strip()
                    if txt:
                        result.append(txt)
            doc.close()
            return result
        doc.close()
    except Exception:
        pass
    return []


def _pdf_page_margin_force_ocr(pdf_bytes: bytes, page_index_zero: int,
                                margin_fraction: float = 0.12) -> str:
    """Force OCR on the bottom margin of a PDF page."""
    if fitz is None or not OCR_AVAILABLE:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if 0 <= page_index_zero < doc.page_count:
            page = doc.load_page(page_index_zero)
            page_img = pdf_page_to_numpy(page, dpi=OCR_DPI)
            doc.close()
            crop_y = int(page_img.shape[0] * (1 - margin_fraction))
            margin_img = page_img[crop_y:, :, :]
            txt = ocr_single_page_text(margin_img)
            del page_img, margin_img
            return txt
        doc.close()
    except Exception:
        pass
    return ""


def _pdf_page_text_or_ocr(pdf_bytes: bytes, page_index_zero: int) -> str:
    """Extract text from a PDF page, falling back to OCR if needed."""
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if 0 <= page_index_zero < doc.page_count:
                page = doc.load_page(page_index_zero)
                txt = page.get_text("text") or ""
                if txt.strip():
                    doc.close()
                    return txt
                # Fallback: OCR via OnnxTR
                if OCR_AVAILABLE:
                    page_img = pdf_page_to_numpy(page, dpi=OCR_DPI)
                    ocr_txt = ocr_single_page_text(page_img)
                    del page_img
                    doc.close()
                    return ocr_txt
            doc.close()
        except Exception:
            pass
    return ""


def _pdf_page_force_ocr(pdf_bytes: bytes, page_index_zero: int) -> str:
    """Force OCR on a PDF page, ignoring any native text layer.

    Used when native text extraction finds page content but no Bates
    candidates — the Bates overlay (pikepdf Form XObject) may not be
    extractable by PyMuPDF's get_text().
    """
    if fitz is None or not OCR_AVAILABLE:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if 0 <= page_index_zero < doc.page_count:
            page = doc.load_page(page_index_zero)
            page_img = pdf_page_to_numpy(page, dpi=OCR_DPI)
            ocr_txt = ocr_single_page_text(page_img)
            del page_img
            doc.close()
            return ocr_txt
        doc.close()
    except Exception:
        pass
    return ""


def _image_bytes_text_ocr(img_bytes: bytes) -> str:
    """Extract text from image bytes using OCR."""
    if not OCR_AVAILABLE:
        return ""
    try:
        page_img = image_bytes_to_numpy(img_bytes)
        return ocr_single_page_text(page_img)
    except Exception:
        pass
    return ""


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """Get the page count of a PDF."""
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            count = doc.page_count
            doc.close()
            return count
        except Exception:
            pass
    try:
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return 1
