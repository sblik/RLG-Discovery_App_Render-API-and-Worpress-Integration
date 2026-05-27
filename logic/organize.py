"""
Year-based file organization.

Contains: Functions to organize files into folders by year extracted from
filename, metadata, or content.
"""
from __future__ import annotations

import logging
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from .utils import _zip_dir
from .dates import extract_year_cascading

logger = logging.getLogger(__name__)


def organize_by_year(
    files: List[Tuple[str, bytes]],
    min_year: int,
    max_year: int,
    year_policy: str,
    unknown_folder: str
) -> tuple:
    """
    Organize files by year detected from filename, metadata, or content.

    Args:
        files: List of (filename, file_bytes) tuples
        min_year: Minimum valid year
        max_year: Maximum valid year
        year_policy: "first", "last", or "max" - how to choose when multiple years found
        unknown_folder: Folder name for files with no detectable year

    Returns:
        Tuple of (zip_bytes, failures) where failures maps filename → reason
        for any file that could not be placed due to an unexpected error.
        Note: files with no detectable year are placed in unknown_folder and
        are NOT counted as failures — that is normal, expected behaviour.
    """
    logger.info("organize_by_year: %d file(s), policy=%r, year range %d–%d",
                len(files), year_policy, min_year, max_year)

    # failures only records genuine processing errors, not "no year found"
    # (which is handled gracefully by placing the file in unknown_folder).
    failures: Dict[str, str] = {}
    folder_counts: Counter = Counter()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        out_root = tmp / f"organized_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out_root.mkdir(parents=True, exist_ok=True)

        for display_name, data in files:
            try:
                # Use cascading extraction: filename → metadata → content
                result = extract_year_cascading(
                    Path(display_name).name,
                    data,
                    min_year,
                    max_year,
                    year_policy
                )

                folder = str(result.year) if result.year is not None else unknown_folder
                logger.info(
                    "organize: '%s' → folder='%s' (method=%s)",
                    display_name, folder, result.method,
                )
            except Exception as e:
                # Unexpected error during year extraction — place in unknown
                # folder so the file still makes it into the output, and record
                # the failure so the caller can report it via X-Failed-Files.
                logger.warning("organize: year extraction error for '%s': %s", display_name, e)
                failures[display_name] = f"Year extraction error: {type(e).__name__}"
                folder = unknown_folder

            folder_counts[folder] += 1
            target_dir = out_root / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / Path(display_name).name
            i = 1
            while dest.exists():
                dest = target_dir / f"{Path(display_name).stem}__{i}{Path(display_name).suffix}"
                i += 1
            dest.write_bytes(data)

        logger.info(
            "organize_by_year: complete — %s, failures: %d",
            dict(sorted(folder_counts.items())), len(failures),
        )
        return _zip_dir(out_root), failures
