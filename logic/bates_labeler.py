"""
Bates labeling/stamping functionality.

Contains: Functions to apply Bates number labels to PDFs and images.
"""
from __future__ import annotations

import io
import os
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import Color

from .utils import (
    load_font,
    natural_key,
    _format_label,
    _pil_dpi,
    _is_mac_resource_junk,
    _zip_dir,
)

# Optional: pikepdf for PDF manipulation
try:
    import pikepdf
    from pikepdf import Page as PikePage, Rectangle as PikeRectangle
    PIKEPDF_AVAILABLE = True
except Exception:
    pikepdf = None
    PikePage = PikeRectangle = None
    PIKEPDF_AVAILABLE = False

# ------------------------
# Constants
# ------------------------
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


# ------------------------
# Data structures
# ------------------------
@dataclass
class BatesRecord:
    """Record of Bates labeling for a single file."""
    rel_dir: str
    filename: str
    pages_or_files: int
    first_label: str
    last_label: str
    category: str  # deepest folder


# ------------------------
# Internal helpers
# ------------------------
def _page_size(page) -> Tuple[float, float]:
    """Get page dimensions from PyPDF2 page."""
    return float(page.mediabox.width), float(page.mediabox.height)


def _overlay_pdf(
    label: str,
    w: float, h: float,
    font_name: str, font_size: int,
    label_x: float, label_y: float,
    color_rgb: Tuple[int, int, int],
    left_punch_margin: float = 0.0,
    border_all_pt: float = 0.0,
) -> bytes:
    """Create a PDF overlay with the Bates label and return as bytes.

    Args:
        label: The Bates label text
        w, h: Page dimensions (MediaBox width/height)
        font_name, font_size: Font settings
        label_x: X position for right edge of label (in page coordinates)
        label_y: Y position for baseline of label (in page coordinates)
        color_rgb: Label color as (r, g, b) tuple
        left_punch_margin: Optional left margin for 3-hole punch
        border_all_pt: Optional border around all edges
    """
    from io import BytesIO
    r, g, b = color_rgb
    packet = BytesIO()
    can = rl_canvas.Canvas(packet, pagesize=(w, h))

    if border_all_pt and border_all_pt > 0:
        can.setFillColor(Color(1, 1, 1))
        B = float(border_all_pt)
        can.rect(0, h - B, w, B, stroke=0, fill=1)
        can.rect(0, 0, w, B, stroke=0, fill=1)
        can.rect(0, 0, B, h, stroke=0, fill=1)
        can.rect(w - B, 0, B, h, stroke=0, fill=1)

    # Draw white rectangle to cover left margin area for punch margin
    if left_punch_margin and left_punch_margin > 0:
        can.setFillColor(Color(1, 1, 1))
        can.rect(0, 0, left_punch_margin, h, stroke=0, fill=1)

    can.setFont(font_name, font_size)
    can.setFillColor(Color(r/255, g/255, b/255))
    can.drawRightString(label_x, label_y, label)

    can.save()
    return packet.getvalue()


def _label_image(
    in_file: Path, out_file: Path, label: str,
    font_name: str, font_size_pt: int,
    margin_right_pt: float, margin_bottom_pt: float,
    color_rgb: Tuple[int, int, int],
    left_punch_margin_pt: float = 0.0,
    border_all_pt: float = 0.0,
):
    """Apply a Bates label to an image file."""
    img = Image.open(in_file)
    img = ImageOps.exif_transpose(img)

    dpi = _pil_dpi(img)
    px_per_point = dpi / 72.0

    mx = int(round(margin_right_pt * px_per_point))
    my = int(round(margin_bottom_pt * px_per_point))
    lp = int(round(left_punch_margin_pt * px_per_point))
    bp = int(round(border_all_pt * px_per_point))

    if lp > 0:
        new_img = Image.new(
            "RGB" if img.mode == "RGB" else "RGBA",
            (img.width + lp, img.height),
            (255, 255, 255) if img.mode != "RGBA" else (255, 255, 255, 0),
        )
        new_img.paste(img, (lp, 0))
        img = new_img

    if bp > 0:
        new_img = Image.new(
            "RGB" if img.mode == "RGB" else "RGBA",
            (img.width + 2 * bp, img.height + 2 * bp),
            (255, 255, 255) if img.mode != "RGBA" else (255, 255, 255, 0),
        )
        new_img.paste(img, (bp, bp))
        img = new_img
        mx = max(mx, bp)
        my = max(my, bp)

    fs_from_points = font_size_pt * px_per_point
    relative_min = 0.025 * min(img.width, img.height)
    fs_px = int(max(10, round(max(fs_from_points, relative_min))))

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    draw = ImageDraw.Draw(img)
    try:
        font = load_font(font_name, fs_px)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = max(0, img.width - mx - tw)
    y = max(0, img.height - my - th)

    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + ox, y + oy), label, font=font, fill=(0, 0, 0))

    draw.text((x, y), label, font=font, fill=color_rgb)

    if out_file.suffix.lower() in [".jpg", ".jpeg"]:
        img.convert("RGB").save(out_file, quality=92, optimize=True)
    else:
        img.save(out_file)


def _measure_text_px(txt: str, font_name: str, font_size_px: int) -> Tuple[int, int]:
    """Measure text dimensions in pixels."""
    try:
        font = load_font(font_name, font_size_px)
    except Exception:
        font = ImageFont.load_default()
    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    return tw, th


def _compute_margins_for_page(
    zone: str, w: float, h: float,
    text: str, font_name: str, font_size: int,
    padding_pt: float, border_pt: float
) -> Tuple[float, float]:
    """Compute margin values for a page based on zone setting."""
    tw, th = _measure_text_px(text, font_name, font_size)

    pad = padding_pt
    border = border_pt

    if zone.startswith("Bottom Left"):
        mr = max(w - pad - tw, border)
        mb = max(pad, border)
    elif zone.startswith("Bottom Center"):
        mr = max((w - tw) / 2.0, border)
        mb = max(pad, border)
    else:  # Bottom Right (default)
        mr = max(pad, border)
        mb = max(pad, border)

    return mr, mb


# ------------------------
# Main labeling function
# ------------------------
def walk_and_label(
    input_zip_or_pdfs: List[Tuple[str, bytes]], *,
    prefix: str, start_num: int, digits: int,
    font_name: str, font_size: int,
    margin_right: float = 18.0, margin_bottom: float = 18.0,
    zone: Optional[str] = None, zone_padding: float = 18.0,
    color_rgb: Tuple[int, int, int],
    left_punch_margin: float = 0.0,
    border_all_pt: float = 0.0,
    diagnostics: bool = False,
) -> Tuple[List[BatesRecord], int, bytes]:
    """
    Apply Bates labels to PDFs and images.

    Args:
        input_zip_or_pdfs: List of (filename, file_bytes) tuples
        prefix: Bates prefix string
        start_num: Starting number
        digits: Number of digits (zero-padded)
        font_name: Font name for labels
        font_size: Font size in points
        margin_right: Right margin in points
        margin_bottom: Bottom margin in points
        zone: Optional zone placement ("Bottom Left (Z1)", "Bottom Center (Z2)", "Bottom Right (Z3)")
        zone_padding: Padding when using zones
        color_rgb: Label color as (r, g, b) tuple
        left_punch_margin: Left margin for 3-hole punch
        border_all_pt: Border around all edges
        diagnostics: Enable diagnostic logging

    Returns:
        Tuple of (records, last_used_number, zip_bytes)
    """
    logger = logging.getLogger(__name__)
    if diagnostics:
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
            logger.addHandler(handler)
        logger.debug("=== BATES LABELING DIAGNOSTICS ENABLED ===")
        logger.debug(f"Zone: {zone}, Zone Padding: {zone_padding}, Font: {font_name} {font_size}pt")
        logger.debug(f"Margins: right={margin_right}, bottom={margin_bottom}, left_punch={left_punch_margin}, border={border_all_pt}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        staged = tmp / "staged"
        staged.mkdir(parents=True, exist_ok=True)
        output = tmp / "labeled"
        output.mkdir(parents=True, exist_ok=True)

        staged_count = 0
        for disp, data in input_zip_or_pdfs:
            if _is_mac_resource_junk(disp):
                continue
            p = staged / disp
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            staged_count += 1

        logger.info("Bates labeling: %d file(s) staged", staged_count)

        # Free input data now that everything is on disk
        input_zip_or_pdfs.clear()

        current = start_num
        records: List[BatesRecord] = []
        files_done = 0

        for dirpath, dirnames, filenames in os.walk(staged, topdown=True):
            dirnames[:] = [d for d in sorted(dirnames, key=natural_key) if not _is_mac_resource_junk(d)]
            filenames = [f for f in sorted(filenames, key=natural_key) if not _is_mac_resource_junk(f)]

            rel_dir = str(Path(dirpath).relative_to(staged))
            out_dir = output / rel_dir if rel_dir != "." else output
            out_dir.mkdir(parents=True, exist_ok=True)

            pdfs = [f for f in filenames if f.lower().endswith(".pdf")]
            imgs = [f for f in filenames if Path(f).suffix.lower() in IMAGE_EXTS]

            for fname in pdfs:
                src = Path(dirpath) / fname
                out = out_dir / fname
                first = current
                pages_count = 0

                try:
                    if not PIKEPDF_AVAILABLE:
                        raise RuntimeError("pikepdf is required for Bates labeling")

                    pdf = pikepdf.open(str(src))

                    for page_num, page in enumerate(pdf.pages):
                        mbox = page.mediabox
                        mbox_x1, mbox_y1 = float(mbox[0]), float(mbox[1])
                        mbox_x2, mbox_y2 = float(mbox[2]), float(mbox[3])
                        w = mbox_x2 - mbox_x1
                        h = mbox_y2 - mbox_y1

                        cropbox = getattr(page, 'cropbox', None)
                        if cropbox is not None:
                            crop_x1, crop_y1 = float(cropbox[0]), float(cropbox[1])
                            crop_x2, crop_y2 = float(cropbox[2]), float(cropbox[3])
                        else:
                            crop_x1, crop_y1 = mbox_x1, mbox_y1
                            crop_x2, crop_y2 = mbox_x2, mbox_y2

                        visible_w = crop_x2 - crop_x1
                        visible_h = crop_y2 - crop_y1

                        label = _format_label(prefix, current, digits, with_space=True)

                        mr, mb = margin_right, margin_bottom
                        if zone:
                            mr, mb = _compute_margins_for_page(
                                zone, visible_w, visible_h, label, font_name, font_size, zone_padding, border_all_pt
                            )

                        eff_mr = max(mr, border_all_pt or 0.0)
                        eff_mb = max(mb, border_all_pt or 0.0)

                        if zone and zone.startswith("Bottom Left"):
                            label_x = crop_x1 + eff_mr
                        elif zone and zone.startswith("Bottom Center"):
                            tw, _ = _measure_text_px(label, font_name, font_size)
                            label_x = crop_x1 + (visible_w + tw) / 2.0
                        else:
                            label_x = crop_x2 - eff_mr

                        label_y = crop_y1 + eff_mb

                        overlay_margin = left_punch_margin if left_punch_margin and left_punch_margin > 0 else 0

                        if diagnostics:
                            trimbox = getattr(page, 'trimbox', None)
                            logger.debug(f"--- File: {fname}, Page {page_num + 1} ---")
                            logger.debug(f"  MediaBox: [{mbox_x1:.2f}, {mbox_y1:.2f}, {mbox_x2:.2f}, {mbox_y2:.2f}]")
                            logger.debug(f"  MediaBox dimensions: {w:.2f} x {h:.2f} pts ({w/72:.2f}\" x {h/72:.2f}\")")
                            if cropbox is not None:
                                logger.debug(f"  CropBox: [{crop_x1:.2f}, {crop_y1:.2f}, {crop_x2:.2f}, {crop_y2:.2f}]")
                                logger.debug(f"  CropBox dimensions: {visible_w:.2f} x {visible_h:.2f} pts ({visible_w/72:.2f}\" x {visible_h/72:.2f}\")")
                            if trimbox:
                                logger.debug(f"  TrimBox: {[float(x) for x in trimbox]}")
                            logger.debug(f"  Calculated margins: right={eff_mr:.2f}pt, bottom={eff_mb:.2f}pt")
                            logger.debug(f"  Label '{label}' absolute position: x={label_x:.2f}pt, y={label_y:.2f}pt")
                            logger.debug(f"  Overlay rect: [{mbox_x1:.2f}, {mbox_y1:.2f}, {mbox_x2:.2f}, {mbox_y2:.2f}]")

                        overlay_bytes = _overlay_pdf(
                            label, w, h, font_name, font_size,
                            label_x, label_y, color_rgb,
                            overlay_margin, border_all_pt
                        )

                        overlay_pdf = pikepdf.open(io.BytesIO(overlay_bytes))
                        overlay_page = overlay_pdf.pages[0]

                        dest_page = PikePage(page)
                        dest_page.add_overlay(overlay_page, PikeRectangle(mbox_x1, mbox_y1, mbox_x2, mbox_y2))

                        overlay_pdf.close()
                        current += 1
                        pages_count += 1

                    pdf.save(str(out))
                    pdf.close()

                    files_done += 1
                    logger.info("Bates labeled PDF %d/%d: %s (%d pages)",
                                files_done, staged_count, fname, pages_count)

                except Exception:
                    logger.exception("Failed to label PDF: %s", fname)
                    continue

                last = current - 1
                cat = Path(rel_dir).parts[-1] if rel_dir not in (".", "") and Path(rel_dir).parts else ""

                records.append(BatesRecord(
                    rel_dir=rel_dir,
                    filename=fname,
                    pages_or_files=pages_count,
                    first_label=_format_label(prefix, first, digits, with_space=True),
                    last_label=_format_label(prefix, last, digits, with_space=True),
                    category=cat,
                ))

            for fname in imgs:
                src = Path(dirpath) / fname
                out = out_dir / fname
                first = current

                try:
                    label = _format_label(prefix, current, digits, with_space=True)

                    mr, mb = margin_right, margin_bottom
                    if zone:
                        with Image.open(io.BytesIO(src.read_bytes())) as tmp_img:
                            tmp_img = ImageOps.exif_transpose(tmp_img)
                            dpi = _pil_dpi(tmp_img)
                            px_per_pt = dpi / 72.0
                            w_pt = tmp_img.width / px_per_pt
                            h_pt = tmp_img.height / px_per_pt

                            mr, mb = _compute_margins_for_page(
                                zone, w_pt, h_pt, label, font_name, font_size, zone_padding, border_all_pt
                            )

                    _label_image(
                        src, out, label, font_name, font_size,
                        mr, mb, color_rgb,
                        left_punch_margin, border_all_pt
                    )
                    current += 1
                    files_done += 1
                    logger.info("Bates labeled image %d/%d: %s",
                                files_done, staged_count, fname)
                except Exception:
                    logger.exception("Failed to label image: %s", fname)
                    continue

                last = current - 1
                cat = Path(rel_dir).parts[-1] if rel_dir not in (".", "") and Path(rel_dir).parts else ""

                records.append(BatesRecord(
                    rel_dir=rel_dir,
                    filename=fname,
                    pages_or_files=1,
                    first_label=_format_label(prefix, first, digits, with_space=True),
                    last_label=_format_label(prefix, last, digits, with_space=True),
                    category=cat,
                ))

        zip_bytes = _zip_dir(output)

    return records, current - 1, zip_bytes
