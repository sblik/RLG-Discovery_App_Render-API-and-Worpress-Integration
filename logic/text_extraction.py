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


def _pdf_page_text_blocks(pdf_bytes: bytes, page_index_zero: int) -> list:
    """Return per-block text strings from a PDF page.

    Using blocks instead of a single concatenated string lets callers
    search each block independently, preventing body-text words from
    bleeding into Bates number matches in adjacent blocks.

    Falls back to a single-element list from OCR when native text is empty.
    """
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if 0 <= page_index_zero < doc.page_count:
                page = doc.load_page(page_index_zero)
                blocks = page.get_text("blocks")
                # block: (x0, y0, x1, y1, text, block_no, block_type)
                texts = [str(b[4]).strip() for b in blocks
                         if len(b) >= 7 and b[6] == 0 and str(b[4]).strip()]
                if texts:
                    doc.close()
                    return texts
                # Fallback: OCR (returns one string — can't split into blocks)
                if OCR_AVAILABLE:
                    page_img = pdf_page_to_numpy(page, dpi=OCR_DPI)
                    ocr_txt = ocr_single_page_text(page_img)
                    del page_img
                    doc.close()
                    return [ocr_txt] if ocr_txt.strip() else []
            doc.close()
        except Exception:
            pass
    return []


def _pdf_page_margin_blocks(
    pdf_bytes: bytes,
    page_index_zero: int,
    margin_fraction: float = 0.12,
) -> list:
    """Return text blocks from the bottom margin of a PDF page.

    Bates stamps are placed in the bottom margin by the labeler, so
    searching only that region eliminates body-text false positives
    (e.g. "TRS Participant ID: 00549327" being mistaken for a bare
    Bates number). Each element is the text of one positioned block
    so callers can search blocks independently and avoid cross-block
    false positives.

    Uses native text extraction only. No OCR fallback — the previous
    OCR fallback (commit 0adcd61) was reverted because cropped-image
    OCR on small margin strips was unreliable. If the stamp was
    baked into a raster image with no text layer, this function
    returns [] and the caller should fall back to a different path.
    """
    if fitz is None:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if not (0 <= page_index_zero < doc.page_count):
                return []
            page = doc.load_page(page_index_zero)
            # fitz PDF coordinate space: y=0 is at the TOP of the page,
            # so "bottom margin" is where y is closest to page.rect.height.
            # A block qualifies if its top edge (block[1]) falls below the
            # margin threshold — that catches stamps that sit entirely
            # within the margin even when they wrap to multiple lines.
            threshold_y = page.rect.height * (1 - margin_fraction)
            blocks = page.get_text("blocks")
            result = []
            for b in blocks:
                # block: (x0, y0, x1, y1, text, block_no, block_type)
                if len(b) < 7 or b[6] != 0:
                    continue
                if b[1] < threshold_y:
                    continue
                txt = str(b[4]).strip()
                if txt:
                    result.append(txt)
            return result
        finally:
            doc.close()
    except Exception:
        return []


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
