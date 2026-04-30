"""
General utility functions for the logic package.

Contains: font loading, zip helpers, color parsing, macOS junk filters,
natural sorting, and other shared utilities.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageFont

# ------------------------
# Font loading
# ------------------------
def load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Load a font from common system paths or fallback to default.
    """
    is_bold = "Bold" in font_name or "bold" in font_name

    candidates = [
        font_name,
        # macOS
        f"/Library/Fonts/{font_name}.ttf",
        f"/System/Library/Fonts/{font_name}.ttf",
        # Linux (Debian/Ubuntu/Render)
        f"/usr/share/fonts/truetype/msttcorefonts/{font_name}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if is_bold
            else f"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if is_bold
            else f"/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    try:
        return ImageFont.truetype(f"{font_name}.ttf", size)
    except Exception:
        pass

    return ImageFont.load_default()


# ------------------------
# Zip utilities
# ------------------------
def _zip_dir(dir_path: Path) -> bytes:
    """Create a ZIP archive from a directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in dir_path.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(dir_path))
    buf.seek(0)
    return buf.read()


def _zip_dir_to_path(dir_path: Path, *, suffix: str = ".zip") -> Path:
    """Like `_zip_dir`, but stream the archive to a tempfile on disk.

    Returns the path to the (closed) tempfile. The caller is responsible
    for deleting it. Used by endpoints that build large output zips so
    the entire archive never sits in RAM while the response streams.
    """
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="zipdir_")
    os.close(fd)
    out = Path(tmp_path)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in dir_path.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(dir_path))
    return out


def _zip_from_pairs(pairs: List[Tuple[str, bytes]]) -> bytes:
    """Create a ZIP archive from a list of (relative_path, bytes) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, b in pairs:
            if rel.endswith("/"):
                continue
            zf.writestr(rel, b)
    buf.seek(0)
    return buf.read()


# ------------------------
# Color utilities
# ------------------------
def _color_from_hex(hex_str: str) -> Tuple[int, int, int]:
    """Parse a hex color string to RGB tuple."""
    hex_str = hex_str.strip("#")
    if len(hex_str) == 6:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return (r, g, b)
    return (0, 0, 255)


# ------------------------
# Sorting
# ------------------------
def natural_key(s: str):
    """Key function for natural sorting of strings with numbers."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


# ------------------------
# System detection
# ------------------------
def _detect_poppler_path() -> Optional[str]:
    """Detect poppler installation path for pdf2image."""
    for c in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(c, "pdftoppm").exists():
            return c
    return None


# ------------------------
# Label formatting
# ------------------------
def _format_label(prefix: str, number: int, digits: int, with_space: bool = True) -> str:
    """Format a Bates label string."""
    return f"{prefix}{' ' if with_space else ''}{number:0{digits}d}"


# ------------------------
# Image utilities
# ------------------------
def _pil_dpi(image: Image.Image) -> float:
    """Extract DPI from PIL image, defaulting to 150."""
    dpi = image.info.get("dpi")
    if isinstance(dpi, tuple) and dpi and dpi[0]:
        return float(dpi[0])
    return 150.0


# ------------------------
# macOS junk filters
# ------------------------
def _is_mac_resource_junk(path_str: str) -> bool:
    """Check if a path is macOS resource fork or junk file."""
    p = str(path_str).replace("\\", "/")
    base = Path(p).name
    if "/__MACOSX/" in p:
        return True
    if base.startswith("._"):
        return True
    if base.lower() == ".ds_store":
        return True
    return False


def _is_bates_sidecar(path_str: str) -> bool:
    """Check if a zip entry is the Bates records sidecar (__bates_records.json)."""
    p = str(path_str).replace("\\", "/").lstrip("./")
    return p == "__bates_records.json"


def _filter_pairs_nonjunk(pairs: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    """Filter out macOS junk files from a list of file pairs."""
    return [(rel, b) for rel, b in pairs if not _is_mac_resource_junk(rel)]
