"""
OCR processing functionality using ocrmypdf.

Contains: Functions to perform OCR on scanned PDFs and create searchable PDF/A documents.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .utils import _is_mac_resource_junk

try:
    import ocrmypdf
    OCRMYPDF_AVAILABLE = True
except Exception:
    ocrmypdf = None
    OCRMYPDF_AVAILABLE = False


@dataclass
class OcrResult:
    """Record of an OCR operation."""
    rel_path: str
    status: str  # "success", "skipped", "error"
    message: str


def ocr_pdf_bytes(
    pdf_bytes: bytes,
    *,
    deskew: bool = False,
    optimize: int = 1,
    language: str = "eng",
    rotate_pages: bool = True,
    remove_background: bool = False,
    force_ocr: bool = False,
    skip_text: bool = False,
) -> Tuple[bytes, OcrResult]:
    """
    Perform OCR on PDF bytes and return searchable PDF.

    Args:
        pdf_bytes: Input PDF file bytes
        deskew: Straighten rotated/skewed scans
        optimize: Optimization level (0-3)
        language: Tesseract language code(s)
        rotate_pages: Auto-rotate pages to correct orientation
        remove_background: Remove background from scans
        force_ocr: OCR all pages regardless of existing text
        skip_text: Skip pages that already have a text layer

    Returns:
        Tuple of (output_pdf_bytes, OcrResult)
    """
    if not OCRMYPDF_AVAILABLE:
        raise RuntimeError("ocrmypdf is not installed. Install with: pip install ocrmypdf")

    result = OcrResult(rel_path="", status="success", message="")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as in_tmp:
        in_tmp.write(pdf_bytes)
        in_path = Path(in_tmp.name)

    out_path = in_path.with_suffix(".ocr.pdf")

    try:
        exit_code = ocrmypdf.ocr(
            input_file=str(in_path),
            output_file=str(out_path),
            deskew=deskew,
            optimize=optimize,
            language=language,
            rotate_pages=rotate_pages,
            remove_background=remove_background,
            force_ocr=force_ocr,
            skip_text=skip_text,
            progress_bar=False,
            jobs=4,
        )

        with open(out_path, "rb") as f:
            output_bytes = f.read()
        result.status = "success"
        result.message = "OCR completed successfully"

    except ocrmypdf.exceptions.PriorOcrFoundError:
        output_bytes = pdf_bytes
        result.status = "skipped"
        result.message = "PDF already has a text layer"

    except ocrmypdf.exceptions.InputFileError as e:
        output_bytes = pdf_bytes
        result.status = "error"
        result.message = f"Input file error: {e}"

    except Exception as e:
        output_bytes = pdf_bytes
        result.status = "error"
        result.message = str(e)

    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    return output_bytes, result


def process_ocr_zip_bytes(
    zip_bytes: bytes,
    *,
    deskew: bool = False,
    optimize: int = 1,
    language: str = "eng",
    rotate_pages: bool = True,
    remove_background: bool = False,
    force_ocr: bool = False,
    skip_text: bool = False,
) -> Tuple[bytes, List[OcrResult], Dict]:
    """
    Process a ZIP file and OCR all PDFs within.

    Args:
        zip_bytes: ZIP file bytes
        deskew: Straighten rotated/skewed scans
        optimize: Optimization level (0-3)
        language: Tesseract language code(s)
        rotate_pages: Auto-rotate pages to correct orientation
        remove_background: Remove background from scans
        force_ocr: OCR all pages regardless of existing text
        skip_text: Skip pages that already have a text layer

    Returns:
        Tuple of (output_zip_bytes, list_of_results, summary_dict)
    """
    processed_files: List[Tuple[str, bytes]] = []
    results: List[OcrResult] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin:
        for info in zin.infolist():
            if info.is_dir():
                continue
            if _is_mac_resource_junk(info.filename):
                continue

            ext = Path(info.filename).suffix.lower()
            if ext != ".pdf":
                processed_files.append((info.filename, zin.read(info)))
                continue

            try:
                pdf_data = zin.read(info)
                ocr_data, result = ocr_pdf_bytes(
                    pdf_data,
                    deskew=deskew,
                    optimize=optimize,
                    language=language,
                    rotate_pages=rotate_pages,
                    remove_background=remove_background,
                    force_ocr=force_ocr,
                    skip_text=skip_text,
                )
                result.rel_path = info.filename
                results.append(result)
                processed_files.append((info.filename, ocr_data))

            except Exception as e:
                results.append(OcrResult(
                    rel_path=info.filename,
                    status="error",
                    message=str(e),
                ))
                processed_files.append((info.filename, zin.read(info)))

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for arcname, data in processed_files:
            zout.writestr(arcname, data)

        report = {
            "files_processed": len([r for r in results if r.status == "success"]),
            "files_skipped": len([r for r in results if r.status == "skipped"]),
            "files_errored": len([r for r in results if r.status == "error"]),
            "settings": {
                "deskew": deskew,
                "optimize": optimize,
                "language": language,
                "rotate_pages": rotate_pages,
                "remove_background": remove_background,
                "force_ocr": force_ocr,
                "skip_text": skip_text,
            },
        }
        zout.writestr("ocr_report.json", json.dumps(report, indent=2).encode("utf-8"))

    summary = {
        "total_files": len(results),
        "success_count": len([r for r in results if r.status == "success"]),
        "skipped_count": len([r for r in results if r.status == "skipped"]),
        "error_count": len([r for r in results if r.status == "error"]),
    }

    return out_buf.getvalue(), results, summary
