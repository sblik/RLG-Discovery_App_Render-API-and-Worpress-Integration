"""
OCR processing functionality using ocrmypdf.

Minimal implementation: upload PDF(s), run OCR with sensible defaults, return result.
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from .utils import _is_mac_resource_junk

# Ensure tesseract is findable on PATH (Docker/Render may install to various locations)
def _ensure_tesseract_on_path():
    if shutil.which("tesseract"):
        return
    for _candidate in ["/usr/bin", "/usr/local/bin", "/opt/render/project/.apt/usr/bin"]:
        if os.path.isfile(os.path.join(_candidate, "tesseract")):
            os.environ["PATH"] = _candidate + os.pathsep + os.environ.get("PATH", "")
            return

_ensure_tesseract_on_path()

try:
    import ocrmypdf
    OCRMYPDF_AVAILABLE = True
except Exception:
    ocrmypdf = None
    OCRMYPDF_AVAILABLE = False


def ocr_pdf_bytes(pdf_bytes: bytes) -> bytes:
    """
    Perform OCR on PDF bytes and return searchable PDF bytes.

    Uses hardcoded defaults: deskew=True, force_ocr=True.
    If the PDF already has OCR text (PriorOcrFoundError), returns original bytes.
    Other exceptions propagate to the caller.
    """
    if not OCRMYPDF_AVAILABLE:
        raise RuntimeError("ocrmypdf is not installed. Install with: pip install ocrmypdf")

    _ensure_tesseract_on_path()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as in_tmp:
        in_tmp.write(pdf_bytes)
        in_path = Path(in_tmp.name)

    out_path = in_path.with_suffix(".ocr.pdf")

    try:
        ocrmypdf.ocr(
            str(in_path),
            str(out_path),
            deskew=True,
            force_ocr=True,
            clean_final=True,
            rotate_pages=True,
            oversample=300,
            progress_bar=False,
            jobs=2,
        )
        with open(out_path, "rb") as f:
            return f.read()

    except ocrmypdf.exceptions.PriorOcrFoundError:
        return pdf_bytes

    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


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
