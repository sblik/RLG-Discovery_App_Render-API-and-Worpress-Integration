"""
Year-based file organization.

Contains: Functions to organize files into folders by year extracted from
filename, metadata, or content.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from .utils import _zip_dir
from .dates import extract_year_cascading


def organize_by_year(
    files: List[Tuple[str, bytes]],
    min_year: int,
    max_year: int,
    year_policy: str,
    unknown_folder: str
) -> bytes:
    """
    Organize files by year detected from filename, metadata, or content.

    Args:
        files: List of (filename, file_bytes) tuples
        min_year: Minimum valid year
        max_year: Maximum valid year
        year_policy: "first", "last", or "max" - how to choose when multiple years found
        unknown_folder: Folder name for files with no detectable year

    Returns:
        ZIP file bytes containing organized folder structure
    """
    logger = logging.getLogger(__name__)

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

                logger.debug(
                    f"File '{display_name}': year={result.year}, "
                    f"method={result.method}, reason={result.reason}"
                )

                folder = str(result.year) if result.year is not None else unknown_folder
            except Exception as e:
                logger.warning(f"Error extracting year from '{display_name}': {e}")
                folder = unknown_folder

            target_dir = out_root / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / Path(display_name).name
            i = 1
            while dest.exists():
                dest = target_dir / f"{Path(display_name).stem}__{i}{Path(display_name).suffix}"
                i += 1
            dest.write_bytes(data)

        return _zip_dir(out_root)
