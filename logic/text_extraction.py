"""
Text extraction utilities for PDFs and images.

Contains: OCR and text extraction functions used by multiple modules.
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

# Optional: pdf2image (for previews & OCR fallback)
try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except Exception:
    PDF2IMAGE_AVAILABLE = False

# Optional: OCR
try:
    import pytesseract
except Exception:
    pytesseract = None


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
                if pytesseract is not None:
                    pix = page.get_pixmap()
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_txt = pytesseract.image_to_string(img) or ""
                    doc.close()
                    return ocr_txt
            doc.close()
        except Exception:
            pass
    if PDF2IMAGE_AVAILABLE and pytesseract is not None:
        try:
            imgs = convert_from_bytes(pdf_bytes, first_page=page_index_zero+1, last_page=page_index_zero+1, dpi=200)
            if imgs:
                return pytesseract.image_to_string(imgs[0]) or ""
        except Exception:
            pass
    return ""


def _image_bytes_text_ocr(img_bytes: bytes) -> str:
    """Extract text from image bytes using OCR."""
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            im = ImageOps.exif_transpose(im)
            if pytesseract is not None:
                return pytesseract.image_to_string(im) or ""
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
