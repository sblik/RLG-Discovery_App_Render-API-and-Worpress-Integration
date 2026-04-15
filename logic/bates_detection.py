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
from .text_extraction import (
    _pdf_page_text_blocks,
    _pdf_page_margin_blocks,
    _image_bytes_text_ocr,
    get_pdf_page_count,
)

# ------------------------
# Bates detection patterns
# ------------------------
_BLACKLIST_PREFIXES = {
    "MONTHLY", "BOX", "ID", "TARGET", "REQUESTED", "MISC",
    "PAGE", "LOREM", "IPSUM",
}

_CANDIDATE_BATES_RE = re.compile(
    r"\b([A-Z][A-Z0-9.]{0,20})[ \t\-–—]+([0-9]{6,10})\b"
)

# Bare zero-padded numbers (no prefix) — used as fallback
_BARE_BATES_RE = re.compile(r"\b(0\d{5,9})\b")


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


def _extract_bare_bates(
    blocks_first: list, blocks_last: list
) -> Tuple[Optional[str], Optional[str]]:
    """Detect bare zero-padded Bates numbers (no prefix) from page blocks."""
    # Bates numbering always starts at >= 1, so reject all-zero matches
    # that come from OCR noise or body-text artifacts (e.g. "000000").
    def _iter_valid(blk: str):
        for m in _BARE_BATES_RE.finditer(blk):
            num = m.group(1)
            if int(num) > 0:
                yield num

    bare_1 = []
    for blk in blocks_first:
        bare_1.extend(_iter_valid(blk))
    bare_N = []
    for blk in blocks_last:
        bare_N.extend(_iter_valid(blk))

    if not bare_1 and not bare_N:
        return None, None

    first = bare_1[0] if bare_1 else bare_N[0]
    last = bare_N[-1] if bare_N else bare_1[-1]
    try:
        if int(last) < int(first):
            first, last = last, first
    except Exception:
        pass
    return first, last


def _extract_bates_for_file(rel_path: str, data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract first and last Bates numbers from a file.

    Returns: (first_bates, last_bates) tuple
    """
    ext = Path(rel_path).suffix.lower()

    if ext == ".pdf":
        # Restrict detection to the bottom margin of the page, where the
        # labeler actually places its stamps. Searching the full page
        # picked up body-text tokens like "TRS Participant ID: 00549327"
        # or "LOT 000136" as false Bates labels. Margin-only blocks
        # eliminates that whole class of false positive at the source.
        blocks_1 = _pdf_page_margin_blocks(data, 0)
        c1 = []
        for blk in blocks_1:
            c1.extend(_extract_candidates(blk))

        page_count = get_pdf_page_count(data)
        last_index = max(0, page_count - 1)

        blocks_N = _pdf_page_margin_blocks(data, last_index)
        cN = []
        for blk in blocks_N:
            cN.extend(_extract_candidates(blk))

        all_cands = c1 + cN
        dom = _choose_dominant_prefix(all_cands)

        if dom:
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

        # Fallback: bare zero-padded numbers (labels with no prefix).
        # Also restricted to margin blocks, so bare numbers in page
        # headers/body/footnotes can't be mistaken for Bates stamps.
        return _extract_bare_bates(blocks_1, blocks_N)

    elif ext in {".jpg", ".jpeg", ".png"}:
        txt = _image_bytes_text_ocr(data)
        cands = _extract_candidates(txt)
        dom = _choose_dominant_prefix(cands)
        if dom:
            tok = _best_token_for_prefix(cands, dom)
            return tok, tok
        # Fallback: bare zero-padded numbers
        return _extract_bare_bates([txt], [txt])

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
