"""
Smart Bates number detection from documents.

Contains: Functions to detect and extract Bates numbers from PDFs and images
using text extraction and OCR.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .utils import _is_mac_resource_junk
from .text_extraction import _pdf_page_text_or_ocr, _image_bytes_text_ocr, get_pdf_page_count

# ------------------------
# Bates detection patterns
# ------------------------
_BLACKLIST_PREFIXES = {
    "MONTHLY", "BOX", "ID", "TARGET", "REQUESTED", "MISC"
}

_CANDIDATE_BATES_RE = re.compile(
    r"\b([A-Z][A-Z0-9. ]{1,30}?)[\s\-–—]*([0-9]{6,10})\b"
)


def _normalize_prefix(s: str) -> str:
    """Normalize a Bates prefix string."""
    s = re.sub(r"\s+", " ", s).strip(" -–—.")
    return s.upper()


def _is_zero_padded(num: str) -> bool:
    """Check if a number string is zero-padded (starts with 0)."""
    return len(num) >= 6 and num[0] == "0"


def _extract_candidates(text: str) -> List[Tuple[str, str]]:
    """Extract candidate Bates numbers from text."""
    out: List[Tuple[str, str]] = []
    if not text:
        return out
    for m in _CANDIDATE_BATES_RE.finditer(text.upper()):
        pfx = _normalize_prefix(m.group(1))
        num = m.group(2)
        out.append((pfx, num))
    return out


def _choose_dominant_prefix(cands: List[Tuple[str, str]]) -> Optional[str]:
    """Choose the most likely Bates prefix from candidates."""
    if not cands:
        return None
    zp = [p for p, n in cands if _is_zero_padded(n) and p not in _BLACKLIST_PREFIXES]
    if zp:
        return Counter(zp).most_common(1)[0][0]
    nb = [p for p, _ in cands if p not in _BLACKLIST_PREFIXES]
    if nb:
        return Counter(nb).most_common(1)[0][0]
    return None


def _best_token_for_prefix(cands: List[Tuple[str, str]], want_prefix: str) -> Optional[str]:
    """Find the best Bates token for a given prefix."""
    for pfx, num in cands:
        if pfx == want_prefix and _is_zero_padded(num):
            return f"{pfx} {num}"
    for pfx, num in cands:
        if pfx == want_prefix:
            return f"{pfx} {num}"
    return None


def _extract_bates_for_file(rel_path: str, data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract first and last Bates numbers from a file.

    Returns: (first_bates, last_bates) tuple
    """
    ext = Path(rel_path).suffix.lower()

    if ext == ".pdf":
        txt1 = _pdf_page_text_or_ocr(data, 0)
        c1 = _extract_candidates(txt1)

        page_count = get_pdf_page_count(data)
        last_index = max(0, page_count - 1)

        txtN = _pdf_page_text_or_ocr(data, last_index)
        cN = _extract_candidates(txtN)

        all_cands = c1 + cN
        dom = _choose_dominant_prefix(all_cands)
        if not dom:
            return None, None

        first_tok = _best_token_for_prefix(c1, dom) or _best_token_for_prefix(all_cands, dom)
        last_tok = _best_token_for_prefix(cN, dom) or _best_token_for_prefix(all_cands[::-1], dom)

        if not first_tok and not last_tok:
            return None, None
        if first_tok and not last_tok:
            return first_tok, first_tok
        if last_tok and not first_tok:
            return last_tok, last_tok

        def _num_part(tok: str) -> int:
            return int(re.search(r"(\d{6,10})$", tok).group(1))

        try:
            n1 = _num_part(first_tok)
            n2 = _num_part(last_tok)
            if n2 < n1:
                first_tok, last_tok = last_tok, first_tok
        except Exception:
            pass
        return first_tok, last_tok

    elif ext in {".jpg", ".jpeg", ".png"}:
        txt = _image_bytes_text_ocr(data)
        cands = _extract_candidates(txt)
        dom = _choose_dominant_prefix(cands)
        if dom:
            tok = _best_token_for_prefix(cands, dom)
            return tok, tok
        return None, None

    else:
        return None, None


def scan_pairs_for_bates(pairs: List[Tuple[str, bytes]]) -> pd.DataFrame:
    """
    Scan a list of file pairs for Bates numbers.

    Args:
        pairs: List of (relative_path, file_bytes) tuples

    Returns:
        DataFrame with columns: rel_dir, filename, first_label, last_label
    """
    rows: List[Dict[str, str]] = []
    for i, (rel, b) in enumerate(pairs, start=1):
        if _is_mac_resource_junk(rel):
            continue
        p = Path(rel)
        rel_dir = str(p.parent) if str(p.parent) != "." else ""
        fname = p.name
        try:
            first, last = _extract_bates_for_file(rel, b)
        except Exception:
            first, last = None, None
        rows.append({
            "rel_dir": rel_dir,
            "filename": fname,
            "first_label": first or "",
            "last_label": last or ""
        })
    return pd.DataFrame(rows)
