"""
Date parsing and year extraction utilities.

Contains: date parsing from text, PDF date parsing, year extraction
from filenames, metadata, and content.
"""
from __future__ import annotations

import io
import re
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Tuple

from PyPDF2 import PdfReader

# Import text extraction for content-based year extraction
from .text_extraction import _pdf_page_text_or_ocr

# ------------------------
# Date parsing
# ------------------------
def _parse_date_from_text(text: str) -> Optional[date]:
    """Parse a date from text string, trying various formats."""
    if not text:
        return None
    # yyyy.mm.dd | yyyy-mm-dd | yyyy_mm_dd
    for m in re.finditer(r"\b(20\d{2}|19\d{2})[._/-](\d{1,2})[._/-](\d{1,2})\b", text):
        y, mo, d = map(int, m.groups())
        try:
            return datetime(y, mo, d).date()
        except ValueError:
            pass
    # yyyymmdd
    m = re.search(r"\b(20\d{2}|19\d{2})(\d{2})(\d{2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date()
        except ValueError:
            pass
    # mm.dd.yyyy | etc
    for m in re.finditer(r"\b(\d{1,2})[._/-](\d{1,2})[._/-](20\d{2}|19\d{2})\b", text):
        mo, d, y = map(int, m.groups())
        try:
            return datetime(y, mo, d).date()
        except ValueError:
            pass
    return None


def _extract_date_produced_from_rel(rel_dir: str, filename: str = "") -> Optional[date]:
    """Extract date produced from relative directory path and filename."""
    parts = Path(rel_dir).parts if rel_dir else ()
    candidates: List[str] = []
    # Explicit: 2nd-level inside the parent folder (index 1)
    if len(parts) >= 2:
        candidates.append(parts[1])
    # fallbacks
    candidates.extend(parts)
    if filename:
        candidates.append(filename)
    for token in candidates:
        d = _parse_date_from_text(token)
        if d:
            return d
    return None


def _parse_pdf_date(date_str: str) -> Optional[int]:
    """
    Parse PDF date format and extract year.

    PDF date format: D:YYYYMMDDHHmmSS or variations like:
    - D:YYYY
    - D:YYYYMM
    - D:YYYYMMDD
    - D:YYYYMMDDHHmmSS
    - D:YYYYMMDDHHmmSS+HH'mm' (with timezone)

    Returns: year as int, or None if parsing fails
    """
    if not date_str:
        return None

    # Remove 'D:' prefix if present
    if date_str.startswith("D:"):
        date_str = date_str[2:]

    # Try to extract the year (first 4 digits)
    match = re.match(r"(\d{4})", date_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None


# ------------------------
# Year extraction patterns
# ------------------------
MONTHS = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?"
PATTERNS: List[re.Pattern] = [
    re.compile(rf"(?<!\d)((?P<year>20\d{{2}}|19\d{{2}}))(?!\d)", re.IGNORECASE),
    re.compile(rf"(?<!\d)\d{{1,2}}[ _\.-]\d{{1,2}}[ _\.-](?P<year>20\d{{2}}|19\d{{2}})(?!\d)", re.IGNORECASE),
    re.compile(rf"(?:(?:{MONTHS})\s*\d{{1,2}}[ ,._-]*)?(?P<year>20\d{{2}}|19\d{{2}})", re.IGNORECASE),
]


def preprocess_filename(name: str) -> str:
    """Preprocess filename for year extraction."""
    return re.sub(r"^[A-Za-z]+\d{4,}[ _\.-]*", "", name)


def extract_year_from_name(name: str, min_year: int, max_year: int, year_policy: str = "first") -> Tuple[Optional[int], str]:
    """Extract year from filename using pattern matching."""
    name = preprocess_filename(name)
    candidates: List[Tuple[int, str, Tuple[int, int]]] = []
    for idx, pat in enumerate(PATTERNS, start=1):
        for m in pat.finditer(name):
            y = int(m.group("year"))
            if min_year <= y <= max_year:
                candidates.append((y, f"pattern{idx}", m.span()))
    if not candidates:
        return None, "no-year-found"
    if year_policy == "max":
        chosen = max(candidates, key=lambda t: t[0])
    elif year_policy == "last":
        chosen = candidates[-1]
    else:
        chosen = candidates[0]
    year, patname, span = chosen
    return year, f"{patname}@{span}"


@dataclass
class YearExtractionResult:
    """Result of cascading year extraction from filename, metadata, or content."""
    year: Optional[int]
    method: str  # "filename", "metadata", "content", "none"
    reason: str  # Details about extraction (pattern matched, date found, etc.)


def extract_year_from_metadata(
    file_data: bytes,
    filename: str,
    min_year: int,
    max_year: int
) -> Tuple[Optional[int], str]:
    """
    Extract year from file metadata (modification date preferred over creation).

    For PDFs: Extract from PDF metadata (ModDate, CreationDate)

    Returns: (year or None, reason string)
    """
    ext = Path(filename).suffix.lower()

    # Only handle PDFs for now
    if ext != ".pdf":
        return None, "metadata-extraction-not-supported-for-filetype"

    try:
        reader = PdfReader(io.BytesIO(file_data))
        metadata = reader.metadata

        if metadata is None:
            return None, "no-metadata-found"

        # Try ModDate first (preferred), then CreationDate
        mod_date = metadata.get("/ModDate") or metadata.get("ModDate")
        creation_date = metadata.get("/CreationDate") or metadata.get("CreationDate")

        year_from_mod = None
        year_from_creation = None

        if mod_date:
            year_from_mod = _parse_pdf_date(str(mod_date))

        if creation_date:
            year_from_creation = _parse_pdf_date(str(creation_date))

        # Use modification date if available and in bounds
        if year_from_mod is not None:
            if min_year <= year_from_mod <= max_year:
                return year_from_mod, f"metadata-ModDate:{mod_date}"

        # Fall back to creation date
        if year_from_creation is not None:
            if min_year <= year_from_creation <= max_year:
                return year_from_creation, f"metadata-CreationDate:{creation_date}"
            return None, f"metadata-year-out-of-bounds:{year_from_creation}"

        if year_from_mod is not None:
            return None, f"metadata-year-out-of-bounds:{year_from_mod}"

        return None, "no-date-in-metadata"

    except Exception as e:
        return None, f"metadata-extraction-error:{str(e)[:50]}"


def extract_year_from_pdf_content(
    pdf_data: bytes,
    min_year: int,
    max_year: int,
    year_policy: str,
    timeout_seconds: float = 5.0
) -> Tuple[Optional[int], str]:
    """
    Extract year from PDF content via text extraction or OCR.

    Returns: (year or None, reason string)
    """
    def _extract_with_timeout() -> Tuple[Optional[int], str]:
        try:
            text = _pdf_page_text_or_ocr(pdf_data, 0)

            if not text or not text.strip():
                return None, "content-no-text-extracted"

            candidates: List[Tuple[int, str, int]] = []
            for idx, pat in enumerate(PATTERNS, start=1):
                for m in pat.finditer(text):
                    try:
                        y = int(m.group("year"))
                        if min_year <= y <= max_year:
                            candidates.append((y, f"pattern{idx}", m.start()))
                    except (ValueError, IndexError):
                        continue

            if not candidates:
                return None, "content-no-year-found"

            if year_policy == "max":
                chosen = max(candidates, key=lambda t: t[0])
            elif year_policy == "last":
                candidates_sorted = sorted(candidates, key=lambda t: t[2])
                chosen = candidates_sorted[-1]
            else:
                candidates_sorted = sorted(candidates, key=lambda t: t[2])
                chosen = candidates_sorted[0]

            year, patname, pos = chosen
            return year, f"content-{patname}@pos{pos}"

        except Exception as e:
            return None, f"content-extraction-error:{str(e)[:50]}"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_extract_with_timeout)
            try:
                result = future.result(timeout=timeout_seconds)
                return result
            except concurrent.futures.TimeoutError:
                return None, f"content-extraction-timeout:{timeout_seconds}s"
    except Exception as e:
        return None, f"content-extraction-error:{str(e)[:50]}"


def extract_year_cascading(
    filename: str,
    file_data: bytes,
    min_year: int,
    max_year: int,
    year_policy: str
) -> YearExtractionResult:
    """
    Cascading year extraction: filename → metadata → content (PDF only)

    Returns: YearExtractionResult with year, method used, and reason
    """
    # Step 1: Try filename extraction
    year, reason = extract_year_from_name(Path(filename).name, min_year, max_year, year_policy)
    if year is not None:
        return YearExtractionResult(year=year, method="filename", reason=reason)

    # Step 2: Try metadata extraction
    year, reason = extract_year_from_metadata(file_data, filename, min_year, max_year)
    if year is not None:
        return YearExtractionResult(year=year, method="metadata", reason=reason)

    # Step 3: Try content extraction (PDF only)
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        year, reason = extract_year_from_pdf_content(file_data, min_year, max_year, year_policy)
        if year is not None:
            return YearExtractionResult(year=year, method="content", reason=reason)
        return YearExtractionResult(year=None, method="none", reason=f"all-methods-failed:content-{reason}")

    return YearExtractionResult(year=None, method="none", reason="all-methods-failed:non-pdf-no-content-scan")
