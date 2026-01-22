"""
Logic package for document processing.

This package provides functionality for:
- PDF unlocking (password removal)
- Year-based file organization
- Bates labeling/stamping
- Discovery index generation (Excel)
- Sensitive content redaction

All public APIs are re-exported here for backward compatibility.
Usage: `import logic` or `from logic import ...`
"""
from __future__ import annotations

# Re-export standard library modules used by main.py
from pathlib import Path

# Re-export third-party modules used by main.py
import pandas as pd
import numpy as np

# ------------------------
# Utils module exports
# ------------------------
from .utils import (
    load_font,
    _zip_dir,
    _zip_from_pairs,
    _color_from_hex,
    natural_key,
    _detect_poppler_path,
    _format_label,
    _pil_dpi,
    _is_mac_resource_junk,
    _filter_pairs_nonjunk,
)

# ------------------------
# Text extraction module exports
# ------------------------
from .text_extraction import (
    _pdf_page_text_or_ocr,
    _image_bytes_text_ocr,
    get_pdf_page_count,
)

# ------------------------
# Dates module exports
# ------------------------
from .dates import (
    _parse_date_from_text,
    _extract_date_produced_from_rel,
    _parse_pdf_date,
    MONTHS,
    PATTERNS,
    preprocess_filename,
    extract_year_from_name,
    YearExtractionResult,
    extract_year_from_metadata,
    extract_year_from_pdf_content,
    extract_year_cascading,
)

# ------------------------
# Bates detection module exports
# ------------------------
from .bates_detection import (
    _normalize_prefix,
    _is_zero_padded,
    _extract_candidates,
    _choose_dominant_prefix,
    _best_token_for_prefix,
    _extract_bates_for_file,
    scan_pairs_for_bates,
)

# ------------------------
# PDF unlock module exports
# ------------------------
from .pdf_unlock import (
    unlock_pdfs,
    PIKEPDF_AVAILABLE,
)

# ------------------------
# Organize module exports
# ------------------------
from .organize import (
    organize_by_year,
)

# ------------------------
# Bates labeler module exports
# ------------------------
from .bates_labeler import (
    IMAGE_EXTS,
    BatesRecord,
    walk_and_label,
)

# ------------------------
# Excel module exports
# ------------------------
from .excel import (
    build_discovery_xlsx,
)

# ------------------------
# Redaction module exports
# ------------------------
from .redaction import (
    SSN_CONTEXT_WORDS,
    DEFAULT_REQUIRE_SSN_CONTEXT,
    PRESETS,
    Hit,
    load_patterns,
    image_bytes_to_pdf,
    add_black_redaction,
    add_black_redaction_leftmask,
    prefix_excluding_last_n_digits,
    redact_pdf_bytes,
    process_zip_bytes,
)

# ------------------------
# Module version
# ------------------------
__version__ = "2.0.0"

__all__ = [
    # Standard library re-exports
    "Path",
    # Third-party re-exports
    "pd",
    "np",
    # Utils
    "load_font",
    "_zip_dir",
    "_zip_from_pairs",
    "_color_from_hex",
    "natural_key",
    "_detect_poppler_path",
    "_format_label",
    "_pil_dpi",
    "_is_mac_resource_junk",
    "_filter_pairs_nonjunk",
    # Text extraction
    "_pdf_page_text_or_ocr",
    "_image_bytes_text_ocr",
    "get_pdf_page_count",
    # Dates
    "_parse_date_from_text",
    "_extract_date_produced_from_rel",
    "_parse_pdf_date",
    "MONTHS",
    "PATTERNS",
    "preprocess_filename",
    "extract_year_from_name",
    "YearExtractionResult",
    "extract_year_from_metadata",
    "extract_year_from_pdf_content",
    "extract_year_cascading",
    # Bates detection
    "_normalize_prefix",
    "_is_zero_padded",
    "_extract_candidates",
    "_choose_dominant_prefix",
    "_best_token_for_prefix",
    "_extract_bates_for_file",
    "scan_pairs_for_bates",
    # PDF unlock
    "unlock_pdfs",
    "PIKEPDF_AVAILABLE",
    # Organize
    "organize_by_year",
    # Bates labeler
    "IMAGE_EXTS",
    "BatesRecord",
    "walk_and_label",
    # Excel
    "build_discovery_xlsx",
    # Redaction
    "SSN_CONTEXT_WORDS",
    "DEFAULT_REQUIRE_SSN_CONTEXT",
    "PRESETS",
    "Hit",
    "load_patterns",
    "image_bytes_to_pdf",
    "add_black_redaction",
    "add_black_redaction_leftmask",
    "prefix_excluding_last_n_digits",
    "redact_pdf_bytes",
    "process_zip_bytes",
]
