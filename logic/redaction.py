"""
PDF redaction functionality.

Contains: Functions to redact sensitive content from PDFs using pattern matching.
"""
from __future__ import annotations

import gc
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Iterable

from PIL import Image

from .utils import _is_mac_resource_junk

logger = logging.getLogger(__name__)

# Optional: PyMuPDF
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

# Optional: pikepdf for PDF repair
try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except Exception:
    pikepdf = None
    PIKEPDF_AVAILABLE = False

# Optional: OnnxTR OCR engine
from .ocr_engine import OCR_AVAILABLE, OCR_DPI, pdf_page_to_numpy, ocr_pages_words

# ------------------------
# Constants and patterns
# ------------------------
SSN_CONTEXT_WORDS = re.compile(r"\b(ssn|social\s*security|soc\s*sec|ss#|tin|taxpayer\s*id)(?!\w)", re.I)
DEFAULT_REQUIRE_SSN_CONTEXT = True

# EIN context words — require one of these nearby before redacting an XX-XXXXXXX number.
# This prevents false positives on case numbers, account numbers, and other hyphenated
# 9-digit sequences that are not employer identification numbers.
EIN_CONTEXT_WORDS = re.compile(
    r"\b(ein|employer\s*id|employer\s*identification|federal\s*tax\s*id|fein|tax\s*id)\b",
    re.I,
)

# Presets updated to support pipes/spaces/hyphens and plain 9-digit SSN
# Note: Removed 9\d\d exclusion from SSN patterns - SSA now assigns 9xx prefixes
PRESETS: Dict[str, List[str]] = {
    "SSN": [
        r"(?<!\d)(?!000|666)\d{3}[-\s|](?!00)\d{2}[-\s|](?!0000)\d{4}(?!\d)",
        r"(?<!\d)(?!000|666)\d{3}(?:(?:\s*\|\s*)|(?:\s+)|(?:-))(?!00)\d{2}(?:(?:\s*\|\s*)|(?:\s+)|(?:-))(?!0000)\d{4}(?!\d)",
        r"(?<!\d)(?!000|666)\d{9}(?!\d)",
    ],
    "EIN": [
        # Employer Identification Number: XX-XXXXXXX
        # Context-word check enforced by default (require_ssn_context=True).
        # Set require_ssn_context=False (aggressive mode) to redact without context.
        r"\b\d{2}-\d{7}\b",
    ],
    "Email": [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ],
    "Phone": [
        r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        r"\+1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        r"1-\d{3}-\d{3}-\d{4}",
    ],
    "Date": [r"\b(?:\d{1,2}[/-]){2}\d{2,4}\b", r"\b\d{4}-\d{2}-\d{2}\b"],
    "8-digit number": [r"\b\d{8}\b"],
    # Credit card numbers — major card types with optional spaces/hyphens between groups
    "Credit Card": [
        r"\b4[0-9]{3}(?:[\s\-]?[0-9]{4}){3}\b",                          # Visa
        r"\b5[1-5][0-9]{2}(?:[\s\-]?[0-9]{4}){3}\b",                     # Mastercard (51–55)
        r"\b2[2-7][0-9]{2}(?:[\s\-]?[0-9]{4}){3}\b",                     # Mastercard (2221–2720)
        r"\b3[47][0-9]{2}[\s\-]?[0-9]{6}[\s\-]?[0-9]{5}\b",              # Amex (4-6-5 groups)
        r"\b6(?:011|5[0-9]{2})(?:[\s\-]?[0-9]{4}){3}\b",                 # Discover
    ],
    # Date of Birth — only redacts when a DOB label appears nearby to avoid
    # redacting all dates (use the plain "Date" preset for that).
    "Date of Birth": [
        r"(?i)(?:date\s+of\s+birth|d\.?o\.?b\.?|born\s+on?)[\s:,]+\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}",
        r"(?i)(?:date\s+of\s+birth|d\.?o\.?b\.?)[\s:,]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}",
    ],
}


# ------------------------
# Data structures
# ------------------------
@dataclass
class Hit:
    """Record of a redaction match."""
    rel_path: str
    page_num: int
    pattern: str
    matched_text: str


# ------------------------
# Pattern loading
# ------------------------
def load_patterns(
    preset_keys: List[str],
    text_block: str,
    literals_block: str,
    case_sensitive: bool
) -> List[re.Pattern]:
    """
    Load and compile redaction patterns.

    Args:
        preset_keys: List of preset names ("SSN", "Email", "Phone", etc.)
        text_block: Newline-separated custom regex patterns
        literals_block: Comma or newline-separated literal strings to redact
        case_sensitive: Whether patterns should be case-sensitive

    Returns:
        List of compiled regex patterns
    """
    raw: List[str] = []
    for key in preset_keys:
        # Swagger UI joins multi-select List[str] form fields into a single
        # comma-separated string (e.g. "SSN,EIN,Credit Card").  Split those
        # here so Swagger and the WordPress plugin both work correctly.
        for subkey in re.split(r"\s*,\s*", key.strip()):
            if subkey:
                raw.extend(PRESETS.get(subkey, []))
    if text_block:
        for line in text_block.splitlines():
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            raw.append(s)
    if literals_block:
        for token in re.split(r"[\n,]", literals_block):
            s = token.strip()
            if s:
                raw.append(re.escape(s))
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = [re.compile(p, flags) for p in raw]
    if not compiled:
        raise ValueError("Provide at least one pattern: select a preset, add regex, or include literal strings.")
    return compiled


# ------------------------
# Internal helpers
# ------------------------
def _iter_zip(file: zipfile.ZipFile, allowed_exts: Set[str]) -> Iterable[Tuple[str, bytes]]:
    """Iterate over files in a ZIP with allowed extensions."""
    for info in file.infolist():
        if info.is_dir():
            continue
        if _is_mac_resource_junk(info.filename):
            continue
        ext = Path(info.filename).suffix.lower()
        if ext in allowed_exts:
            yield info.filename, file.read(info)


def image_bytes_to_pdf(img_bytes: bytes) -> bytes:
    """Convert image bytes to PDF bytes."""
    with Image.open(io.BytesIO(img_bytes)) as im:
        rgb = im.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="PDF")
        return buf.getvalue()


PAD_VALUE = 2.0
PAD_VALUE_V = -3.0


def _black_fill():
    """Get black fill color for redaction."""
    try:
        from pymupdf import utils as _u
        return _u.getColor("black")
    except Exception:
        return (0, 0, 0)


def add_black_redaction(page: "fitz.Page", rect: "fitz.Rect", pad: Optional[float] = None) -> None:
    """Add a black redaction box to a page."""
    ph = float(PAD_VALUE if pad is None else pad)
    pv = float(PAD_VALUE_V)
    r = fitz.Rect(rect)
    r = fitz.Rect(r.x0 - ph, r.y0 - pv, r.x1 + ph, r.y1 + pv)
    page.add_redact_annot(r, fill=_black_fill())


def add_black_redaction_leftmask(page: "fitz.Page", rect: "fitz.Rect", pad: Optional[float] = None) -> None:
    """Add a black redaction box with left masking (for partial redaction)."""
    ph = float(PAD_VALUE if pad is None else pad)
    pv = float(PAD_VALUE_V)
    r = fitz.Rect(rect)
    r = fitz.Rect(r.x0 - ph, r.y0 - pv, r.x1, r.y1 + pv)
    page.add_redact_annot(r, fill=_black_fill())


def prefix_excluding_last_n_digits(s: str, n: int) -> str:
    """Get prefix of string excluding the last n digits."""
    if n <= 0:
        return s
    digits_seen = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i].isdigit():
            digits_seen += 1
            if digits_seen == n:
                return s[:i]
    return ""


def _repair_pdf_if_needed(raw: bytes) -> bytes:
    """Attempt to repair a PDF using pikepdf."""
    if not PIKEPDF_AVAILABLE:
        return raw
    try:
        with pikepdf.open(io.BytesIO(raw)) as pdf:
            buf = io.BytesIO()
            pdf.save(buf)
            return buf.getvalue()
    except Exception:
        return raw


_HYPHENS = ["-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2212"]
_SPACES = [" ", "\u00A0"]
_PIPES = ["|", "\u00A6"]


def _search_variants(s: str) -> List[str]:
    """Generate search variants for a string (handling different separators)."""
    s = s.replace("\u200B", "").replace("\u2009", "")
    variants = {s}
    if "-" in s:
        for h in _HYPHENS:
            variants.add(s.replace("-", h))
    for sp in _SPACES:
        variants.add(s.replace(sp, " "))
        variants.add(s.replace(sp, ""))
    if "|" in s:
        for p in _PIPES:
            variants.add(s.replace("|", p))
        variants.add(s.replace("|", " "))
        variants.add(s.replace("|", ""))
    return sorted(variants, key=len, reverse=True)


# ------------------------
# Main redaction functions
# ------------------------
def redact_pdf_bytes(
    pdf_bytes: bytes,
    patterns: List[re.Pattern],
    keep_last_digits: int = 0,
    *,
    require_ssn_context: bool = DEFAULT_REQUIRE_SSN_CONTEXT
) -> Tuple[bytes, List[Hit]]:
    """
    Redact sensitive content from PDF bytes.

    Args:
        pdf_bytes: PDF file bytes
        patterns: List of compiled regex patterns to match
        keep_last_digits: Number of digits to keep visible (for SSN partial redaction)
        require_ssn_context: Whether SSN patterns require context words nearby

    Returns:
        Tuple of (redacted_pdf_bytes, list_of_hits)
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF (pymupdf) is required. Install with: pip install pymupdf")
    hits: List[Hit] = []
    _t0 = time.monotonic()

    SSN_PATTERNS = {p for p in PRESETS["SSN"]}
    EIN_PATTERNS = {p for p in PRESETS["EIN"]}

    def _is_ssn_pat(pat: re.Pattern) -> bool:
        return pat.pattern in SSN_PATTERNS

    def _is_ein_pat(pat: re.Pattern) -> bool:
        return pat.pattern in EIN_PATTERNS

    def _passes_ssn_context_text(full_text: str, m: re.Match) -> bool:
        window = full_text[max(0, m.start()-60): m.end()+60]
        return bool(SSN_CONTEXT_WORDS.search(window))

    def _passes_ein_context_text(full_text: str, m: re.Match) -> bool:
        window = full_text[max(0, m.start()-60): m.end()+60]
        return bool(EIN_CONTEXT_WORDS.search(window))

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        logger.warning("redact_pdf_bytes: PDF failed to open cleanly — attempting repair")
        repaired = _repair_pdf_if_needed(pdf_bytes)
        doc = fitz.open(stream=repaired, filetype="pdf")

    logger.info("redact_pdf_bytes: %d page(s), %d pattern(s), keep_last_digits=%d",
                doc.page_count, len(patterns), keep_last_digits)

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_text = page.get_text("text") or ""
        page_had_text = bool(page_text.strip())

        if not page_had_text and OCR_AVAILABLE:
            try:
                page_img = pdf_page_to_numpy(page, dpi=OCR_DPI)
                ocr_words_list = ocr_pages_words([page_img])[0]
                del page_img
                gc.collect()

                # Build parallel arrays matching the old pytesseract dict layout
                pw = page.rect.width
                ph = page.rect.height
                words = []
                ocr = {"left": [], "top": [], "width": [], "height": []}
                for ow in ocr_words_list:
                    words.append(ow.text)
                    x0 = ow.xmin * pw
                    y0 = ow.ymin * ph
                    x1 = ow.xmax * pw
                    y1 = ow.ymax * ph
                    ocr["left"].append(x0)
                    ocr["top"].append(y0)
                    ocr["width"].append(x1 - x0)
                    ocr["height"].append(y1 - y0)

                for idx, word in enumerate(words):
                    if not word:
                        continue
                    l = ocr["left"][idx]
                    t = ocr["top"][idx]
                    w = ocr["width"][idx]
                    h = ocr["height"][idx]
                    for pat in patterns:
                        if pat.fullmatch(word):
                            if require_ssn_context and _is_ssn_pat(pat):
                                lo = max(0, idx-6)
                                hi = min(len(words), idx+7)
                                snippet = " ".join(wd for wd in words[lo:hi] if wd)
                                if not SSN_CONTEXT_WORDS.search(snippet or ""):
                                    continue
                            if require_ssn_context and _is_ein_pat(pat):
                                lo = max(0, idx-6)
                                hi = min(len(words), idx+7)
                                snippet = " ".join(wd for wd in words[lo:hi] if wd)
                                if not EIN_CONTEXT_WORDS.search(snippet or ""):
                                    continue
                            if keep_last_digits > 0:
                                num_digits = sum(ch.isdigit() for ch in word)
                                if num_digits > keep_last_digits:
                                    redact_ratio = (num_digits - keep_last_digits) / max(num_digits, 1)
                                    rect = fitz.Rect(l, t, l + w * redact_ratio, t + h)
                                    add_black_redaction_leftmask(page, rect)
                                    hits.append(Hit("", page_index + 1, pat.pattern, word))
                                    continue
                            rect = fitz.Rect(l, t, l + w, t + h)
                            add_black_redaction(page, rect)
                            hits.append(Hit("", page_index + 1, pat.pattern, word))

                N = len(words)

                def _bbox(i):
                    return (ocr["left"][i], ocr["top"][i], ocr["width"][i], ocr["height"][i])

                def _nearby_has_ssn_keyword(center_i: int) -> bool:
                    lo = max(0, center_i-6)
                    hi = min(N, center_i+7)
                    snippet = " ".join(w for w in words[lo:hi] if w)
                    return bool(SSN_CONTEXT_WORDS.search(snippet or ""))

                for i in range(0, max(0, N - 4)):
                    w0 = words[i]
                    w1 = words[i+1]
                    w2 = words[i+2]
                    w3 = words[i+3]
                    w4 = words[i+4]
                    if not (w0 and w2 and w4):
                        continue
                    if re.fullmatch(r"\d{3}", w0) and re.fullmatch(r"\D*", w1 or "") \
                       and re.fullmatch(r"\d{2}", w2) and re.fullmatch(r"\D*", w3 or "") \
                       and re.fullmatch(r"\d{4}", w4):
                        if require_ssn_context and not _nearby_has_ssn_keyword(i+2):
                            continue
                        l0, t0, ww0, hh0 = _bbox(i)
                        l1, t1, ww1, hh1 = _bbox(i+1)
                        l2, t2, ww2, hh2 = _bbox(i+2)
                        l3, t3, ww3, hh3 = _bbox(i+3)
                        l4, t4, ww4, hh4 = _bbox(i+4)
                        x0 = min(l0, l1, l2, l3, l4)
                        y0 = min(t0, t1, t2, t3, t4)
                        x1 = max(l0+ww0, l1+ww1, l2+ww2, l3+ww3, l4+ww4)
                        y1 = max(t0+hh0, t1+hh1, t2+hh2, t3+hh3, t4+hh4)
                        add_black_redaction(page, fitz.Rect(x0, y0, x1, y1))
                        hits.append(Hit("", page_index + 1, "OCR_SSN_SPLIT", f"{w0}-{w2}-{w4}"))

            except Exception:
                pass
        else:
            full_targets: List[str] = []
            partial_prefixes: List[str] = []
            for pat in patterns:
                for m in pat.finditer(page_text):
                    s = m.group(0)
                    if not s.strip():
                        continue
                    if require_ssn_context and _is_ssn_pat(pat) and not _passes_ssn_context_text(page_text, m):
                        continue
                    if require_ssn_context and _is_ein_pat(pat) and not _passes_ein_context_text(page_text, m):
                        continue
                    if keep_last_digits > 0:
                        prefix = prefix_excluding_last_n_digits(s, keep_last_digits)
                        if prefix:
                            partial_prefixes.append(prefix)
                            hits.append(Hit("", page_index + 1, pat.pattern, s))
                            continue
                    full_targets.append(s)
                    hits.append(Hit("", page_index + 1, pat.pattern, s))

            for s_lit in set(partial_prefixes):
                if len(re.sub(r"\s+", "", s_lit)) > 60:
                    continue
                for candidate in _search_variants(s_lit):
                    try:
                        rects = page.search_for(candidate, quads=True) or []
                        for q in rects:
                            add_black_redaction_leftmask(page, q.rect)
                        if rects:
                            break
                    except Exception:
                        rects = page.search_for(candidate) or []
                        for r in rects:
                            add_black_redaction_leftmask(page, r)
                        if rects:
                            break

            for s_lit in set(full_targets):
                if len(re.sub(r"\s+", "", s_lit)) > 60:
                    continue
                for candidate in _search_variants(s_lit):
                    try:
                        rects = page.search_for(candidate, quads=True) or []
                        for q in rects:
                            add_black_redaction(page, q.rect)
                        if rects:
                            break
                    except Exception:
                        rects = page.search_for(candidate) or []
                        for r in rects:
                            add_black_redaction(page, r)
                        if rects:
                            break

        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except Exception:
            pass

    try:
        doc.apply_redactions()
    except Exception:
        pass

    out = doc.tobytes()
    doc.close()
    logger.info("redact_pdf_bytes: done — %d hit(s) in %.2f s",
                len(hits), time.monotonic() - _t0)
    return out, hits


def process_zip_bytes(
    zip_bytes: bytes,
    patterns: List[re.Pattern],
    keep_last_digits: int = 0,
    *,
    require_ssn_context: bool = DEFAULT_REQUIRE_SSN_CONTEXT
) -> Tuple[bytes, List[Hit], Dict]:
    """
    Process a ZIP file and redact all PDFs and images within.

    Args:
        zip_bytes: ZIP file bytes
        patterns: List of compiled regex patterns to match
        keep_last_digits: Number of digits to keep visible (for SSN partial redaction)
        require_ssn_context: Whether SSN patterns require context words nearby

    Returns:
        Tuple of (output_zip_bytes, list_of_hits, summary_dict)
    """
    redacted_files: List[Tuple[str, bytes]] = []
    audit_hits: List[Hit] = []
    # failures maps filename → reason for files that could not be redacted.
    # Failed files are omitted from the output ZIP (the batch never aborts).
    failures: Dict[str, str] = {}

    _batch_t0 = time.monotonic()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zin:
        _all_entries = [
            i.filename for i in zin.infolist()
            if not i.is_dir() and not _is_mac_resource_junk(i.filename)
        ]
    logger.info("process_zip_bytes: %d file(s) to redact, %d pattern(s)",
                len(_all_entries), len(patterns))

    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zin:
        for rel_path, data in _iter_zip(zin, {".pdf", ".jpg", ".jpeg", ".png"}):
            ext = Path(rel_path).suffix.lower()
            try:
                if ext == ".pdf":
                    red_pdf, hits = redact_pdf_bytes(data, patterns, keep_last_digits, require_ssn_context=require_ssn_context)
                else:
                    pdf_data = image_bytes_to_pdf(data)
                    red_pdf, hits = redact_pdf_bytes(pdf_data, patterns, keep_last_digits, require_ssn_context=require_ssn_context)

                for h in hits:
                    h.rel_path = rel_path
                audit_hits.extend(hits)

                out_name = str(Path(rel_path).with_suffix(".pdf"))
                redacted_files.append((out_name, red_pdf))
            except Exception as e:
                # Per-file failure: record and continue — don't abort the batch.
                reason = f"Redaction failed: {type(e).__name__}"
                failures[rel_path] = reason
                logger.warning("process_zip_bytes: failed to redact '%s' — %s", rel_path, reason)

    # Build the audit report. Each record captures what was found and where,
    # but never the actual matched text (SSNs and other PII must not appear
    # in the audit file — only pattern name, file, and page number).
    # Records are grouped by (file, page, pattern) to keep the report compact.
    audit_records: Dict[tuple, Dict] = {}
    for h in audit_hits:
        key = (h.rel_path, h.page_num, h.pattern)
        if key in audit_records:
            audit_records[key]["match_count"] += 1
        else:
            audit_records[key] = {
                "file": h.rel_path,
                "page": h.page_num,
                "pattern": h.pattern,
                "match_count": 1,
            }
    audit_json = json.dumps(list(audit_records.values()), indent=2).encode("utf-8")

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for arcname, data in redacted_files:
            zout.writestr(arcname, data)
        # Include the audit report in the output ZIP so attorneys have a record
        # of what was redacted without needing to open each individual PDF.
        zout.writestr("_redaction_audit.json", audit_json)

    logger.info(
        "process_zip_bytes: done — %d file(s) redacted, %d failure(s), %d total hit(s) in %.2f s",
        len(redacted_files), len(failures), len(audit_hits), time.monotonic() - _batch_t0,
    )
    return out_buf.getvalue(), audit_hits, {
        "files_processed": len(redacted_files),
        "total_hits": len(audit_hits),
        "keep_last_digits": keep_last_digits,
        "require_ssn_context": require_ssn_context,
        "failures": failures,
    }
