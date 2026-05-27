"""
Pre-flight scan for the document pipeline.

Contains: scan_files() — inspects a batch of uploaded file pairs before the
heavy pipeline stages run. Returns a ScanManifest describing each file's
properties: page count, lock status, estimated memory footprint, file type,
and size. This information is used by:

  - The /pipeline/scan endpoint to give the UI an instant response while
    the user confirms settings before kicking off the full run.
  - The /pipeline/run endpoint to skip or warn about problematic files
    (e.g. still-encrypted PDFs) rather than failing silently mid-batch.

No OCR, no stamping, no modification — read-only analysis only.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR memory estimate constants
# ---------------------------------------------------------------------------

# At 150 DPI an 8.5×11 page renders to roughly 1275×1650 pixels (≈ 2.1 MP).
# OnnxTR's fast_tiny model uses ~80 MB of working RAM per page for detection
# + recognition at that resolution. We round up to 90 MB to be conservative.
_OCR_MB_PER_PAGE = 90

# Minimum per-file memory floor even for single-page files, covering model
# load overhead and buffers that stay resident regardless of page count.
_OCR_MB_MIN_PER_FILE = 30

# Maximum page count we will inspect from a PDF during the scan. Beyond this
# we stop counting and report the cap value so scan stays sub-second.
_MAX_PAGE_SCAN = 500


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FileScanResult:
    """
    Pre-flight analysis for one file in the batch.

    Attributes:
        filename:       Original filename as it entered the pipeline.
        file_type:      "pdf", "image", or "other". Used to decide which
                        stages apply to this file.
        size_bytes:     Raw file size in bytes.
        page_count:     Number of pages (PDF) or 1 (image). None if the
                        file could not be read.
        is_locked:      True if the PDF is encrypted and requires a password.
        is_already_ocr: True if the PDF already has a searchable text layer
                        and can skip OCR (heuristic — may have false negatives
                        for partially-scanned documents).
        estimated_ocr_mb: Estimated additional RAM (megabytes) needed to OCR
                          this file. 0 for non-PDF/image files or already-OCR
                          PDFs. Used to warn if the batch would exceed RAM.
        error:          If the file could not be analyzed, the error message.
                        The file will still be included in the pipeline run;
                        it will fail at whichever stage first touches it.
    """
    filename: str
    file_type: str = "other"        # "pdf" | "image" | "other"
    size_bytes: int = 0
    page_count: Optional[int] = None
    is_locked: bool = False
    is_already_ocr: bool = False
    estimated_ocr_mb: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON responses."""
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "is_locked": self.is_locked,
            "is_already_ocr": self.is_already_ocr,
            "estimated_ocr_mb": self.estimated_ocr_mb,
            "error": self.error,
        }


@dataclass
class ScanManifest:
    """
    Aggregated results of a pre-flight scan over an entire batch.

    Attributes:
        files:              Per-file scan results (same order as input).
        total_files:        Number of input files scanned.
        total_pages:        Sum of page_count across all scannable files.
        locked_count:       Number of PDFs that require a password.
        already_ocr_count:  Number of PDFs that already have a text layer.
        total_estimated_mb: Sum of estimated_ocr_mb — rough upper bound on
                            RAM needed to OCR the whole batch sequentially.
        warnings:           Human-readable warning strings for conditions the
                            caller should surface to the user (e.g. locked
                            files that will be skipped).
    """
    files: List[FileScanResult] = field(default_factory=list)
    total_files: int = 0
    total_pages: int = 0
    locked_count: int = 0
    already_ocr_count: int = 0
    total_estimated_mb: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON responses."""
        return {
            "total_files": self.total_files,
            "total_pages": self.total_pages,
            "locked_count": self.locked_count,
            "already_ocr_count": self.already_ocr_count,
            "total_estimated_mb": self.total_estimated_mb,
            "warnings": self.warnings,
            "files": [f.to_dict() for f in self.files],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Image extensions the pipeline can process (mirrors bates_labeler.IMAGE_EXTS).
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"}

# Minimum fraction of pages that must have text for is_already_ocr to be True.
# A document with 80%+ text-bearing pages is considered already searchable.
_OCR_TEXT_THRESHOLD = 0.80


def scan_files(file_pairs: List[Tuple[str, bytes]]) -> ScanManifest:
    """
    Perform a read-only pre-flight scan on a batch of files.

    Args:
        file_pairs: List of (filename, file_bytes) tuples, exactly as they
                    would be passed to the pipeline stages.

    Returns:
        A ScanManifest describing each file and aggregate batch statistics.
        Errors on individual files are recorded in FileScanResult.error and
        do NOT raise — the goal is to give as much information as possible
        even when some files are problematic.
    """
    manifest = ScanManifest()
    manifest.total_files = len(file_pairs)

    for filename, data in file_pairs:
        result = FileScanResult(filename=filename, size_bytes=len(data))
        ext = PurePosixPath(filename).suffix.lower()

        if ext == ".pdf":
            result.file_type = "pdf"
            _scan_pdf(result, data)
        elif ext in _IMAGE_EXTS:
            result.file_type = "image"
            result.page_count = 1
            # Images always need OCR (they have no text layer).
            result.estimated_ocr_mb = max(_OCR_MB_PER_PAGE, _OCR_MB_MIN_PER_FILE)
        else:
            result.file_type = "other"
            # Non-PDF/image — nothing to scan; it will pass through untouched.

        # Accumulate aggregate stats.
        if result.page_count is not None:
            manifest.total_pages += result.page_count
        if result.is_locked:
            manifest.locked_count += 1
        if result.is_already_ocr:
            manifest.already_ocr_count += 1
        manifest.total_estimated_mb += result.estimated_ocr_mb
        manifest.files.append(result)

    # Build human-readable warnings that the UI should surface before the run.
    if manifest.locked_count > 0:
        manifest.warnings.append(
            f"{manifest.locked_count} PDF(s) are password-protected and will be "
            f"skipped unless a password is provided via the Unlock stage."
        )
    if manifest.total_estimated_mb > 1800:
        manifest.warnings.append(
            f"Estimated OCR memory usage is {manifest.total_estimated_mb} MB, "
            f"which may be close to the server limit. Consider splitting the "
            f"batch into smaller groups."
        )

    return manifest


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan_pdf(result: FileScanResult, data: bytes) -> None:
    """
    Populate *result* with PDF-specific scan data (in-place).

    Tries pikepdf first for page count and lock detection, then falls back
    to PyMuPDF (fitz) for the is_already_ocr heuristic.
    """
    try:
        import pikepdf
    except ImportError:
        pikepdf = None  # type: ignore

    try:
        import fitz  # PyMuPDF
    except ImportError:
        fitz = None  # type: ignore

    # --- Lock detection and page count via pikepdf -----------------------
    if pikepdf is not None:
        try:
            with pikepdf.open(io.BytesIO(data)) as pdf:
                page_count = min(len(pdf.pages), _MAX_PAGE_SCAN)
                result.page_count = page_count
                result.is_locked = False
        except pikepdf.PasswordError:
            # Document is encrypted and requires a password.
            result.is_locked = True
            result.page_count = None
            logger.debug("Locked PDF detected: %s", result.filename)
            return  # No further analysis possible without the password.
        except Exception as e:
            logger.warning("pikepdf scan failed for '%s': %s", result.filename, e)
            # Fall through to fitz fallback.

    # --- OCR text-layer heuristic via PyMuPDF ----------------------------
    # If pikepdf already gave us a page count, reuse it in the fitz block
    # rather than re-opening the file unnecessarily.
    if fitz is not None and not result.is_locked:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            if result.page_count is None:
                result.page_count = min(doc.page_count, _MAX_PAGE_SCAN)

            # Sample up to 10 evenly-spaced pages to check for existing text.
            # Checking every page would be too slow for large batches.
            pages_to_check = _sample_page_indices(result.page_count, sample=10)
            text_page_count = 0
            for idx in pages_to_check:
                try:
                    page = doc.load_page(idx)
                    text = page.get_text("text")
                    # A page has meaningful text if it contains 50+ non-whitespace chars.
                    if len(text.replace(" ", "").replace("\n", "")) >= 50:
                        text_page_count += 1
                except Exception:
                    pass  # Bad page — skip and continue sampling.

            doc.close()

            # Mark as already-OCR if the majority of sampled pages have text.
            if pages_to_check and (text_page_count / len(pages_to_check)) >= _OCR_TEXT_THRESHOLD:
                result.is_already_ocr = True
        except Exception as e:
            logger.warning("fitz scan failed for '%s': %s", result.filename, e)
            if result.page_count is None:
                result.error = f"Could not read PDF: {type(e).__name__}"

    # --- Memory estimate --------------------------------------------------
    # Only estimate OCR RAM for PDFs that actually need OCR.
    if not result.is_locked and not result.is_already_ocr and result.page_count is not None:
        mb = result.page_count * _OCR_MB_PER_PAGE
        result.estimated_ocr_mb = max(mb, _OCR_MB_MIN_PER_FILE)


def _sample_page_indices(page_count: int, sample: int = 10) -> List[int]:
    """
    Return up to *sample* evenly-spaced page indices in [0, page_count).

    For small documents (≤ sample pages) returns all indices.
    For large documents returns a representative spread.
    """
    if page_count <= sample:
        return list(range(page_count))
    step = page_count / sample
    return [int(i * step) for i in range(sample)]
