"""
OCR processing functionality using OnnxTR + PyMuPDF.

Upload PDF(s), run OCR with deep-learning models, return searchable PDF.
No system binaries required (no Tesseract, Ghostscript, etc.).
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF — primary PDF manipulation library
import numpy as np
from PIL import Image, ImageOps

from .ocr_engine import (
    OCR_AVAILABLE,
    OCR_DPI,
    get_predictor,
    pdf_page_to_numpy,
    ocr_pages_words,
)
from .utils import _is_mac_resource_junk, natural_key, _format_label
from .bates_labeler import BATES_RECORDS_SIDECAR, LETTER_WIDTH_PT, LETTER_HEIGHT_PT, JPEG_QUALITY

logger = logging.getLogger(__name__)

# Image extensions supported by the /ocr endpoint
OCR_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Default Bates label appearance for gap-fill labeling — mirrors /bates
# defaults (Helvetica 12pt blue, 18pt margins). Kept local so /ocr has no
# new form fields.
_DEFAULT_FONT = "helv"              # PyMuPDF built-in Helvetica
_DEFAULT_FONT_SIZE = 12
_DEFAULT_COLOR_RGB = (0.0, 0.0, 1.0)  # blue, fitz uses floats in [0, 1]
_DEFAULT_MARGIN_RIGHT_PT = 18.0
_DEFAULT_MARGIN_BOTTOM_PT = 18.0

_BATES_TOKEN_RE = re.compile(r"^\s*([A-Z][A-Z0-9.]*)?\s*(\d{4,10})\s*$")


@dataclass
class LabelSpec:
    """Rendering parameters for a native-text Bates label on a fitz page."""
    font_name: str = _DEFAULT_FONT
    font_size: int = _DEFAULT_FONT_SIZE
    color_rgb: Tuple[float, float, float] = _DEFAULT_COLOR_RGB
    margin_right_pt: float = _DEFAULT_MARGIN_RIGHT_PT
    margin_bottom_pt: float = _DEFAULT_MARGIN_BOTTOM_PT


def _draw_bates_label(page: "fitz.Page", label: str, spec: LabelSpec) -> None:
    """Draw ``label`` as native PDF text at the bottom-right of ``page``.

    Uses fitz coordinates (top-left origin). Label baseline sits
    ``margin_bottom_pt`` above the bottom edge, right edge of the text sits
    ``margin_right_pt`` left of the right edge — matches /bates placement.
    """
    if not label:
        return
    text_w = fitz.get_text_length(
        label, fontname=spec.font_name, fontsize=spec.font_size,
    )
    x = page.rect.width - spec.margin_right_pt - text_w
    y = page.rect.height - spec.margin_bottom_pt
    page.insert_text(
        fitz.Point(x, y), label,
        fontname=spec.font_name,
        fontsize=spec.font_size,
        color=spec.color_rgb,
    )


def _insert_ocr_text_layer(page: "fitz.Page", words: list, img_rect=None) -> None:
    """Insert invisible OCR text onto a fitz page."""
    if not words:
        return
    rect = img_rect or page.rect
    pw = rect.width
    ph = rect.height
    ox, oy = rect.x0, rect.y0
    for w in words:
        x0, y0 = ox + w.xmin * pw, oy + w.ymin * ph
        x1, y1 = ox + w.xmax * pw, oy + w.ymax * ph
        target_w = x1 - x0
        target_h = y1 - y0
        if target_w <= 0 or target_h <= 0 or not w.text:
            continue
        # Font size based on height — keeps line heights consistent
        fontsize = max(1.0, target_h * 0.8)
        # Append a trailing space so PyMuPDF's text extractor preserves
        # word boundaries. Without it, OnnxTR's tight word boxes cause
        # adjacent words to merge on extraction (e.g. "PlaintiffAcme").
        text = w.text + " "
        # Horizontal scale to match bounding box width
        text_w = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        h_scale = (target_w / text_w) if text_w > 0 else 1.0
        morph = (fitz.Point(x0, y1), fitz.Matrix(h_scale, 1.0))
        page.insert_text(
            fitz.Point(x0, y1), text,
            fontname="helv", fontsize=fontsize,
            render_mode=3, morph=morph,
        )


def ocr_pdf_bytes(
    pdf_bytes: bytes,
    dpi: int = OCR_DPI,
    labels: Optional[List[str]] = None,
    label_spec: Optional[LabelSpec] = None,
) -> bytes:
    """
    Perform OCR on PDF bytes and return searchable PDF bytes.

    Pages that already contain extractable text are left untouched.
    Text-less pages are rendered to images, run through OnnxTR, and an
    invisible text layer is inserted so the PDF becomes searchable.

    Pages are processed one at a time to keep memory usage low.

    When ``labels`` is provided (one string per page), each non-empty entry
    is drawn as a native-text Bates stamp at the bottom-right of the
    corresponding page. Used by the /ocr gap-fill path to stamp loose PDFs
    that weren't in the input sidecar.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    spec = label_spec or LabelSpec()
    have_labels = bool(labels)
    n_pages = doc.page_count

    ocr_needed = False
    for page_index in range(n_pages):
        page = doc.load_page(page_index)
        existing_text = (page.get_text("text") or "").strip()
        if not existing_text:
            ocr_needed = True
            break

    if not ocr_needed and not have_labels:
        logger.info("ocr_pdf_bytes: %d page(s) — all pages already searchable, skipping OCR", n_pages)
        out = doc.tobytes()
        doc.close()
        return out

    n_ocr = 0
    # Process one page at a time to minimise memory usage
    for page_index in range(n_pages):
        page = doc.load_page(page_index)
        existing_text = (page.get_text("text") or "").strip()
        if not existing_text:
            n_ocr += 1
            logger.debug("ocr_pdf_bytes: running OCR on page %d/%d", page_index + 1, n_pages)
            page_img = pdf_page_to_numpy(page, dpi=dpi)
            words_list = ocr_pages_words([page_img])
            del page_img
            if words_list and words_list[0]:
                _insert_ocr_text_layer(page, words_list[0])

        if have_labels and page_index < len(labels):
            _draw_bates_label(page, labels[page_index], spec)

    logger.info("ocr_pdf_bytes: %d page(s) processed — %d needed OCR, %d already had text",
                n_pages, n_ocr, n_pages - n_ocr)
    out = doc.tobytes()
    doc.close()
    return out


def ocr_image_bytes(
    img_bytes: bytes,
    dpi: int = OCR_DPI,
    label: Optional[str] = None,
    label_spec: Optional[LabelSpec] = None,
) -> bytes:
    """
    OCR a single-frame image (JPG, PNG) and return a searchable PDF.

    The image is embedded into a PDF page at its native resolution, then an
    invisible OCR text layer is placed on top.

    When ``label`` is provided, a native-text Bates stamp is drawn at the
    bottom-right of the page — used by /ocr gap-fill so image files carry
    labels that /index can read without re-OCR'ing.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    # Open, fix orientation, ensure RGB
    im = Image.open(io.BytesIO(img_bytes))
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        im = im.convert("RGB")

    # Page dimensions in points (1 inch = 72 pt)
    width_pt = im.width * 72.0 / dpi
    height_pt = im.height * 72.0 / dpi

    # Define the target PDF size (US Letter, from shared constants)
    letter_w = LETTER_WIDTH_PT
    letter_h = LETTER_HEIGHT_PT

    # Fit image inside the letter page (scale up or down as needed)
    scale = min(letter_w / width_pt, letter_h / height_pt)

    # Re-encode to JPEG (EXIF transpose may have rotated)
    jpeg_buf = io.BytesIO()
    im.save(jpeg_buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg_bytes = jpeg_buf.getvalue()

    # Convert to numpy for OCR, then release PIL image
    page_img = np.array(im)
    del im

    # Build PDF page with the image
    doc = fitz.open()
    page = doc.new_page(width=letter_w, height=letter_h)
    scaled_w = width_pt * scale
    scaled_h = height_pt * scale
    x_offset = (letter_w - scaled_w) / 2
    y_offset = (letter_h - scaled_h) / 2
    img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_w, y_offset + scaled_h)
    page.insert_image(img_rect, stream=jpeg_bytes)
    del jpeg_bytes

    # Run OCR and insert text layer
    words_list = ocr_pages_words([page_img])
    del page_img

    if words_list and words_list[0]:
        _insert_ocr_text_layer(page, words_list[0], img_rect)

    if label:
        _draw_bates_label(page, label, label_spec or LabelSpec())

    out = doc.tobytes()
    doc.close()
    return out


def ocr_tiff_bytes(
    img_bytes: bytes,
    dpi: int = OCR_DPI,
    label: Optional[str] = None,
    label_spec: Optional[LabelSpec] = None,
) -> bytes:
    """
    OCR a TIFF image (single or multi-page) and return a searchable PDF.

    Each TIFF frame becomes one PDF page with the image embedded and an
    invisible OCR text layer on top.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "onnxtr is not installed. Install with: pip install 'onnxtr[cpu-headless]'"
        )

    im = Image.open(io.BytesIO(img_bytes))

    # Single-frame TIFF — delegate to the simpler path
    if getattr(im, "n_frames", 1) == 1:
        im.close()
        return ocr_image_bytes(img_bytes, dpi=dpi, label=label, label_spec=label_spec)

    # Multi-frame TIFF
    doc = fitz.open()
    n_frames = im.n_frames

    for frame_idx in range(n_frames):
        im.seek(frame_idx)
        frame = im.copy()
        frame = ImageOps.exif_transpose(frame)
        if frame.mode != "RGB":
            frame = frame.convert("RGB")

        width_pt = frame.width * 72.0 / dpi
        height_pt = frame.height * 72.0 / dpi

        # Define the target PDF size (US Letter, from shared constants)
        letter_w = LETTER_WIDTH_PT
        letter_h = LETTER_HEIGHT_PT

        # Fit image inside the letter page (scale up or down as needed)
        scale = min(letter_w / width_pt, letter_h / height_pt)

        # Re-encode frame to JPEG
        jpeg_buf = io.BytesIO()
        frame.save(jpeg_buf, format="JPEG", quality=JPEG_QUALITY)
        jpeg_bytes = jpeg_buf.getvalue()

        # Convert to numpy for OCR
        frame_np = np.array(frame)
        del frame

        # Add page with embedded image
        page = doc.new_page(width=letter_w, height=letter_h)
        scaled_w = width_pt * scale
        scaled_h = height_pt * scale
        x_offset = (letter_w - scaled_w) / 2
        y_offset = (letter_h - scaled_h) / 2
        img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_w, y_offset + scaled_h)
        page.insert_image(img_rect, stream=jpeg_bytes)
        del jpeg_bytes

        # Run OCR and insert text layer
        words_list = ocr_pages_words([frame_np])
        del frame_np

        if words_list and words_list[0]:
            _insert_ocr_text_layer(page, words_list[0], img_rect)

        if label:
            _draw_bates_label(page, label, label_spec or LabelSpec())

    del im

    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Sidecar-aware gap-fill helpers
# ---------------------------------------------------------------------------

def _norm_zip_path(path_str: str) -> str:
    """Normalize a zip member name to forward-slash, no leading './'."""
    return str(path_str or "").replace("\\", "/").lstrip("./")


def _parse_token(tok: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Parse a Bates token like 'TMN 000185' or '000185'.

    Returns (prefix, number, digit_width). digit_width is the number of
    zero-padded digits in the numeric portion (used to preserve formatting
    when generating new labels).
    """
    if not tok:
        return None, None, None
    m = _BATES_TOKEN_RE.match(str(tok))
    if not m:
        return None, None, None
    pfx = (m.group(1) or "").strip()
    num_str = m.group(2) or ""
    try:
        num = int(num_str)
    except (TypeError, ValueError):
        return None, None, None
    return pfx, num, len(num_str)


def _infer_numbering(
    records: List[dict],
) -> Tuple[str, int, int]:
    """Infer (prefix, digits, next_number) from sidecar records.

    next_number = max(last_label_number) + 1 across all records.
    prefix = most common prefix string (may be "").
    digits = digit-width used by the dominant prefix's labels.
    """
    prefixes: List[str] = []
    digits_by_prefix: Dict[str, List[int]] = {}
    max_num = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        first = str(rec.get("first_label", "") or "")
        last = str(rec.get("last_label", "") or first)
        for tok in (first, last):
            pfx, num, dig = _parse_token(tok)
            if pfx is None:
                continue
            prefixes.append(pfx)
            digits_by_prefix.setdefault(pfx, []).append(dig)
            if num is not None and num > max_num:
                max_num = num

    if not prefixes:
        return "", 8, 1

    dominant = Counter(prefixes).most_common(1)[0][0]
    digs_for_dom = digits_by_prefix.get(dominant, [8])
    digits = Counter(digs_for_dom).most_common(1)[0][0]
    return dominant, digits, max_num + 1


def _extract_sidecar_from_pairs(
    file_pairs: List[Tuple[str, bytes]],
) -> Tuple[Optional[List[dict]], List[Tuple[str, bytes]]]:
    """Pull the Bates sidecar out of ``file_pairs`` if present.

    Returns (records_list_or_None, pairs_without_sidecar). Only the first
    sidecar encountered is used; any additional ones are dropped with a
    warning.
    """
    sidecar_records: Optional[List[dict]] = None
    remaining: List[Tuple[str, bytes]] = []
    for name, data in file_pairs:
        norm = _norm_zip_path(name)
        if Path(norm).name == BATES_RECORDS_SIDECAR:
            if sidecar_records is not None:
                logger.warning("Multiple Bates sidecars in zip; keeping first")
                continue
            try:
                parsed = json.loads(data.decode("utf-8"))
                if isinstance(parsed, list):
                    sidecar_records = parsed
                else:
                    logger.warning("Bates sidecar is not a list; ignoring")
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to parse bates sidecar %s: %s", name, e)
            continue
        remaining.append((name, data))
    return sidecar_records, remaining


def _build_sidecar_lookup(records: List[dict]) -> Dict[str, dict]:
    """Build a path-keyed lookup of sidecar entries (keys normalized)."""
    lookup: Dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        path = rec.get("path") or ""
        if not path:
            rel_dir = rec.get("rel_dir", "") or ""
            fname = rec.get("filename", "") or ""
            path = f"{rel_dir}/{fname}" if rel_dir else fname
        lookup[_norm_zip_path(path)] = rec
    return lookup


def _make_record(out_name: str, first_label: str, last_label: str, pages: int) -> dict:
    """Build a sidecar record for a newly-labeled file."""
    norm = _norm_zip_path(out_name)
    p = Path(norm)
    rel_dir = str(p.parent).replace("\\", "/") if str(p.parent) != "." else ""
    rel_dir = rel_dir.strip("/")
    cat = p.parts[-2] if len(p.parts) > 1 else ""
    return {
        "path": norm,
        "rel_dir": rel_dir,
        "filename": p.name,
        "first_label": first_label,
        "last_label": last_label,
        "pages": pages,
        "category": cat,
    }


def _rekey_record_for_ext_change(rec: dict, new_out_name: str) -> dict:
    """Update an existing sidecar record so its path matches ``new_out_name``.

    Used when an image file is converted to PDF — sidecar path/filename must
    reflect the new extension so downstream /index can match records to
    files in the output zip.
    """
    norm = _norm_zip_path(new_out_name)
    p = Path(norm)
    new_rec = dict(rec)
    new_rec["path"] = norm
    new_rec["filename"] = p.name
    rel_dir = str(p.parent).replace("\\", "/") if str(p.parent) != "." else ""
    new_rec["rel_dir"] = rel_dir.strip("/")
    return new_rec


def _page_count_pdf(pdf_bytes: bytes) -> int:
    try:
        d = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = d.page_count
        d.close()
        return n
    except Exception:
        return 1


# Minimum non-whitespace characters a page must contain for us to consider
# it "already searchable". Pages with only a handful of chars may have a tiny
# invisible text artifact rather than a real text layer (e.g. some metadata).
_OCR_TEXT_MIN_CHARS = 20


def _pdf_is_fully_searchable(pdf_bytes: bytes) -> bool:
    """
    Return True if every page of the PDF already has a usable text layer.

    This is the pre-check used before dispatching to OnnxTR so we can skip
    OCR (and report it clearly to the user) for PDFs that macOS, Apple Notes,
    or other tools have already made searchable.

    A page is considered searchable if its extracted text contains at least
    ``_OCR_TEXT_MIN_CHARS`` non-whitespace characters. Pages with only a
    handful of characters may have stray metadata rather than real OCR output,
    so we treat those as needing OCR.

    Returns False on any read error so the file falls through to the normal
    OCR path rather than being silently passed through with no text layer.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            non_ws = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
            if non_ws < _OCR_TEXT_MIN_CHARS:
                doc.close()
                return False
        doc.close()
        return True
    except Exception:
        return False


def _ocr_one(
    fname: str,
    data: bytes,
    *,
    label: Optional[str] = None,
    labels: Optional[List[str]] = None,
    label_spec: Optional[LabelSpec] = None,
) -> Tuple[str, bytes]:
    """OCR a single file (PDF or image), optionally drawing a Bates label.

    Returns (out_name, out_bytes). Image files are re-extensioned to .pdf
    because that's what the OCR path produces. Unknown extensions pass
    through unchanged.
    """
    ext = Path(fname).suffix.lower()
    if ext == ".pdf":
        out_data = ocr_pdf_bytes(data, labels=labels, label_spec=label_spec)
        return fname, out_data
    if ext in OCR_IMAGE_EXTS:
        out_name = str(Path(fname).with_suffix(".pdf"))
        try:
            if ext in (".tif", ".tiff"):
                out_data = ocr_tiff_bytes(data, label=label, label_spec=label_spec)
            else:
                out_data = ocr_image_bytes(data, label=label, label_spec=label_spec)
            return out_name, out_data
        except Exception:
            logger.warning("Failed to OCR image %s, passing through", fname)
            return fname, data
    return fname, data


def process_file_pairs(
    file_pairs: List[Tuple[str, bytes]],
) -> tuple:
    """OCR every file. If a Bates sidecar is present in the input, activate
    gap-fill mode: label files missing from the sidecar with continued
    numbering, redraw sidecar-listed image labels as native PDF text so
    /index can read them downstream, and re-emit an updated sidecar.

    Returns a 3-tuple: (result_pairs, failures, already_searchable).

    * result_pairs   — list of (out_name, out_bytes) ready to be zipped.
    * failures       — maps filename → reason for every file that could not
                       be processed. A single failure never aborts the batch.
    * already_searchable — maps filename → human-readable reason for PDFs that
                       were skipped because they already had a complete text
                       layer (e.g. Apple automatically OCR'd them). These files
                       are passed through unchanged and are NOT failures — the
                       caller should surface this distinction to the user so
                       attorneys know which files were truly processed vs.
                       silently passed through.
    """
    sidecar_records, pairs = _extract_sidecar_from_pairs(file_pairs)
    failures: Dict[str, str] = {}
    already_searchable: Dict[str, str] = {}

    mode = "plain" if sidecar_records is None else "gap-fill"
    logger.info("process_file_pairs: %d file(s), mode=%s", len(pairs), mode)

    # Plain OCR mode — no sidecar, no labeling
    if sidecar_records is None:
        results = []
        for name, data in pairs:
            ext = Path(name).suffix.lower()
            # Before running OCR (which is expensive), check whether this PDF
            # already has a complete text layer. Apple's macOS, Preview, and
            # Photos apps all run OCR automatically, so many client-provided
            # PDFs arrive fully searchable. Running OnnxTR on them wastes RAM,
            # takes time, and risks overwriting existing text with lower-quality
            # model output. Pass them through unchanged and report clearly.
            if ext == ".pdf" and _pdf_is_fully_searchable(data):
                already_searchable[name] = (
                    "Already searchable — OCR skipped "
                    "(all pages have an existing text layer)"
                )
                logger.info("Skipping OCR for '%s' — all pages already have text", name)
                results.append((name, data))
                continue
            try:
                logger.info("process_file_pairs: OCR-ing '%s'", name)
                results.append(_ocr_one(name, data))
            except Exception as e:
                failures[name] = f"OCR failed: {type(e).__name__}"
                logger.exception("OCR failed for %s", name)

        logger.info(
            "process_file_pairs: done — %d processed, %d already searchable, %d failed",
            len(results) - len(already_searchable), len(already_searchable), len(failures),
        )
        return results, failures, already_searchable

    # Gap-fill mode
    sidecar_lookup = _build_sidecar_lookup(sidecar_records)
    prefix, digits, next_num = _infer_numbering(sidecar_records)
    logger.info(
        "OCR gap-fill: sidecar has %d entries; inferred prefix=%r digits=%d next_num=%d",
        len(sidecar_records), prefix, digits, next_num,
    )

    spec = LabelSpec()
    # Preserve existing sidecar entries; update any that get re-extensioned
    # (image -> PDF). Append fresh entries for loose files we newly stamp.
    updated_records: List[dict] = []
    handled_keys = set()

    # Sort pairs for deterministic gap-fill numbering
    pairs_sorted = sorted(pairs, key=lambda x: natural_key(_norm_zip_path(x[0])))

    results: List[Tuple[str, bytes]] = []
    for name, data in pairs_sorted:
        norm = _norm_zip_path(name)
        ext = Path(norm).suffix.lower()
        sidecar_entry = sidecar_lookup.get(norm)

        try:
            if sidecar_entry is not None:
                handled_keys.add(norm)
                first_label = str(sidecar_entry.get("first_label", "") or "")

                if ext == ".pdf":
                    # Pre-labeled PDF — OCR text-less pages, leave stamp alone.
                    out_name, out_data = _ocr_one(name, data)
                    updated_records.append(sidecar_entry)
                    results.append((out_name, out_data))
                    continue

                if ext in OCR_IMAGE_EXTS:
                    # Pre-labeled image — burned-pixel stamp isn't reliably
                    # OCR'd, so redraw the sidecar's authoritative label as
                    # native PDF text. /index reads that cleanly.
                    out_name, out_data = _ocr_one(
                        name, data, label=first_label, label_spec=spec,
                    )
                    updated_records.append(_rekey_record_for_ext_change(sidecar_entry, out_name))
                    results.append((out_name, out_data))
                    continue

                # Other files — pass through, keep sidecar entry as-is
                updated_records.append(sidecar_entry)
                results.append((name, data))
                continue

            # Loose file — not in sidecar. OCR + stamp with next-in-sequence.
            if ext == ".pdf":
                pages = _page_count_pdf(data)
                labels = [
                    _format_label(prefix, next_num + i, digits, with_space=True)
                    for i in range(pages)
                ]
                first_label = labels[0] if labels else ""
                last_label = labels[-1] if labels else ""
                out_name, out_data = _ocr_one(
                    name, data, labels=labels, label_spec=spec,
                )
                results.append((out_name, out_data))
                updated_records.append(_make_record(out_name, first_label, last_label, pages))
                next_num += pages
                continue

            if ext in OCR_IMAGE_EXTS:
                label = _format_label(prefix, next_num, digits, with_space=True)
                out_name, out_data = _ocr_one(
                    name, data, label=label, label_spec=spec,
                )
                results.append((out_name, out_data))
                updated_records.append(_make_record(out_name, label, label, 1))
                next_num += 1
                continue

            # Unknown extension — pass through without labeling
            results.append((name, data))

        except Exception as e:
            # Per-file failure: log it, record it, and continue with the batch.
            failures[name] = f"OCR failed: {type(e).__name__}"
            logger.exception("OCR gap-fill failed for %s", name)

    # Re-emit updated sidecar at the zip root
    sidecar_bytes = json.dumps(updated_records, ensure_ascii=False, indent=2).encode("utf-8")
    results.append((BATES_RECORDS_SIDECAR, sidecar_bytes))

    # Gap-fill mode processes every file in the sidecar regardless of whether
    # it already had a text layer (because it may also need a Bates label drawn
    # as native text). already_searchable is empty here by design.
    return results, failures, {}


def process_ocr_zip_bytes(zip_bytes: bytes) -> bytes:
    """
    Process a ZIP file: OCR all PDFs within, pass non-PDFs through unchanged.

    Writes each result to the output ZIP incrementally to avoid accumulating
    all processed files in memory simultaneously.
    """
    out_buf = io.BytesIO()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin:
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.is_dir():
                    continue
                if _is_mac_resource_junk(info.filename):
                    continue

                file_data = zin.read(info)
                ext = Path(info.filename).suffix.lower()
                out_name = info.filename

                if ext == ".pdf":
                    file_data = ocr_pdf_bytes(file_data)
                elif ext in OCR_IMAGE_EXTS:
                    try:
                        if ext in (".tif", ".tiff"):
                            file_data = ocr_tiff_bytes(file_data)
                        else:
                            file_data = ocr_image_bytes(file_data)
                        out_name = str(Path(info.filename).with_suffix(".pdf"))
                    except Exception:
                        logger.warning("Failed to OCR image %s, passing through", info.filename)

                zout.writestr(out_name, file_data)
                del file_data

    return out_buf.getvalue()
