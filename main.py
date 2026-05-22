from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response
from typing import List, Optional
import asyncio
import io
import logging
import os
import zipfile
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import business logic
import logic
from logic.ocr_engine import OCR_AVAILABLE, get_predictor

# Eagerly load OCR models at startup so memory is accounted for
# before any request arrives (avoids OOM from model load + inference combined)
if OCR_AVAILABLE:
    try:
        logger.info("Pre-loading OCR predictor...")
        get_predictor()
        logger.info("OCR predictor ready.")
    except Exception:
        logger.exception("Failed to pre-load OCR predictor")

app = FastAPI(
    title="SCOUT",
    description="API for legal document processing: Unlock, Organize, Bates Stamp, Redact.",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=False,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
    expose_headers=["Content-Disposition", "X-Last-Bates-Number", "X-Total-Hits", "X-Unlock-Failed-Count", "X-Bates-Failed-Count", "X-OCR-Failed-Count"],
)

_SINGLE_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

OCR_CONCURRENCY = int(os.environ.get("OCR_CONCURRENCY", "1"))
_ocr_semaphore = asyncio.Semaphore(OCR_CONCURRENCY)

def _output_name(files: list, suffix: str, ext: str = ".zip") -> str:
    """Build a download filename from the first uploaded file's name + a tool suffix.

    Examples:
        _output_name(files, "_LABELED")        -> "Case_Documents_LABELED.zip"
        _output_name(files, "_index", ".xlsx")  -> "Case_Documents_index.xlsx"
    """
    from pathlib import PurePosixPath
    raw = files[0].filename if files else ""
    stem = PurePosixPath(raw).stem or "output"
    return f"{stem}{suffix}{ext}"


def _maybe_unwrap_single_file(zip_bytes: bytes):
    """If ZIP contains one supported file, return (bytes, filename, media_type). Otherwise None."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        entries = [i for i in zf.infolist() if not i.is_dir()]
        if len(entries) == 1:
            ext = entries[0].filename.rsplit(".", 1)[-1].lower() if "." in entries[0].filename else ""
            media_type = _SINGLE_FILE_TYPES.get(f".{ext}")
            if media_type:
                name = entries[0].filename.split('/')[-1]
                return zf.read(entries[0]), name, media_type
    return None


def _maybe_unwrap_single_file_path(zip_path):
    """Path-based variant: opens the zip from disk and only materializes
    bytes for the one entry (if there is one supported entry)."""
    from pathlib import Path as _P
    with zipfile.ZipFile(str(zip_path)) as zf:
        entries = [i for i in zf.infolist() if not i.is_dir()]
        if len(entries) == 1:
            ext = entries[0].filename.rsplit(".", 1)[-1].lower() if "." in entries[0].filename else ""
            media_type = _SINGLE_FILE_TYPES.get(f".{ext}")
            if media_type:
                name = entries[0].filename.split('/')[-1]
                return zf.read(entries[0]), name, media_type
    return None

@app.get("/")
def home():
    return {
        "message": "Discovery One-Stop API is running.",
        "endpoints": [
            "/unlock",
            "/organize",
            "/bates",
            "/index",
            "/redact",
            "/ocr"
        ]
    }

# -----------------------------------------------------------------------------
# 1. UNLOCK
# -----------------------------------------------------------------------------
@app.post("/unlock")
async def unlock_pdfs_endpoint(
    files: List[UploadFile] = File(...),
    password_mode: str = Form("Single password for all"),  # "Single password for all", "Per-file password list (CSV)", "Try no password"
    password_for_all: Optional[str] = Form(None),
    password_csv: Optional[UploadFile] = File(None)
):
    """
    Unlock PDFs.
    - Upload multiple PDFs or ZIPs.
    - Provide password mode and optional password/CSV.
    - Returns a ZIP of unlocked PDFs.
    """
    # Read files into memory
    file_pairs = []
    for f in files:
        content = await f.read()
        file_pairs.append((f.filename, content))
    
    password_map = {}
    if password_csv:
        content = (await password_csv.read()).decode("utf-8", errors="replace")
        import csv
        reader = csv.reader(content.splitlines())
        header = next(reader, None)
        if header and len(header) >= 2:
            try:
                fn_idx = header.index("filename")
                pw_idx = header.index("password")
            except ValueError:
                fn_idx, pw_idx = 0, 1
            for row in reader:
                if len(row) >= 2:
                    password_map[row[fn_idx]] = row[pw_idx]
        else:
            for row in reader:
                if len(row) >= 2:
                    password_map[row[0]] = row[1]

    try:
        result_zip, succeeded, failures = logic.unlock_pdfs(file_pairs, password_mode, password_for_all, password_map)
        if succeeded == 0:
            detail = 'No files could be unlocked. ' + '; '.join(f"{name}: {reason}" for name, reason in failures)
            raise HTTPException(status_code=422, detail=detail)
        single = _maybe_unwrap_single_file(result_zip)
        if single:
            file_bytes, file_name, media = single
            out_name = _output_name(files, "_unlocked", "." + file_name.rsplit(".", 1)[-1])
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    "X-Unlock-Failed-Count": str(len(failures))
                }
            )

        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={
            "Content-Disposition": f'attachment; filename="{_output_name(files, "_unlocked")}"',
            "X-Unlock-Failed-Count": str(len(failures)),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 2. ORGANIZE
# -----------------------------------------------------------------------------
@app.post("/organize")
async def organize_endpoint(
    files: List[UploadFile] = File(...),
    min_year: int = Form(1900),
    max_year: int = Form(2099),
    year_policy: str = Form("first"),  # "first", "last", "max"
    unknown_folder: str = Form("Unknown")
):
    """
    Organize PDFs by year detected in filename.
    """
    file_pairs = []
    for f in files:
        content = await f.read()
        # Handle ZIP upload if single file is ZIP
        if f.filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Could not read '{f.filename}': it may be corrupt or not a valid ZIP.")
        else:
            file_pairs.append((f.filename, content))

    try:
        result_zip = logic.organize_by_year(file_pairs, min_year, max_year, year_policy, unknown_folder)
        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{_output_name(files, "_organized")}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 3. BATES LABELER
# -----------------------------------------------------------------------------
import re as _re_bates

# Matches "PREFIX 000123" or bare "000123" tokens emitted by the detector.
_BATES_TOKEN_RE = _re_bates.compile(r"^\s*([A-Z][A-Z0-9.]*)?\s*(\d{4,10})\s*$")


def _parse_bates_token(tok: str):
    """Return (prefix, number) parsed from a detected Bates token.

    Detector outputs look like 'TMN 000185' or bare '000185'. Returns
    (prefix_str, int_number) on success, or (None, None) if the token
    doesn't match the expected shape.
    """
    if not tok:
        return None, None
    m = _BATES_TOKEN_RE.match(str(tok))
    if not m:
        return None, None
    pfx = (m.group(1) or "").strip()
    try:
        num = int(m.group(2))
    except (TypeError, ValueError):
        return None, None
    return pfx, num


def _detect_preexisting_bates(
    file_pairs: "list", *, user_prefix: str, user_start: int,
):
    """Detect pre-labeled files in the input and compute effective numbering.

    Runs `logic.scan_pairs_for_bates` over the input pairs. For each file
    that comes back with a non-empty label, records a skip_existing entry
    and tracks the detected prefix + max number. Returns:

        (skip_existing, effective_prefix, effective_start)

    where skip_existing is a dict mapping rel_path -> (first_label, last_label)
    suitable for `walk_and_label`, and effective_prefix / effective_start
    are the values to pass to the labeler for the *unlabeled* files
    (auto-continued from max+1 when any detection succeeded).

    If the input contains no pre-labeled files, skip_existing is empty and
    the user's prefix/start_num are passed through unchanged.
    """
    try:
        det = logic.scan_pairs_for_bates(file_pairs)
    except Exception:
        logger.exception("Bates pre-pass detection failed; falling back to full stamping")
        return {}, user_prefix, user_start

    skip_existing = {}
    detected_prefixes = []
    max_detected = 0

    if det is None or det.empty:
        return {}, user_prefix, user_start

    for _, row in det.iterrows():
        first = (row.get("first_label", "") or "").strip()
        last = (row.get("last_label", "") or first).strip()
        if not first:
            continue
        rel_dir = (row.get("rel_dir", "") or "").replace("\\", "/").strip("/")
        fname = row.get("filename", "") or ""
        key = f"{rel_dir}/{fname}" if rel_dir and rel_dir != "." else fname
        skip_existing[key] = (first, last)

        pfx_f, num_f = _parse_bates_token(first)
        pfx_l, num_l = _parse_bates_token(last)
        if pfx_f is not None:
            detected_prefixes.append(pfx_f)
        if pfx_l is not None:
            detected_prefixes.append(pfx_l)
        if num_l is not None:
            max_detected = max(max_detected, num_l)
        elif num_f is not None:
            max_detected = max(max_detected, num_f)

    if not skip_existing:
        return {}, user_prefix, user_start

    # Pick dominant prefix (most common). Empty string is a valid "bare
    # numbering" prefix.
    from collections import Counter
    prefix_counts = Counter(detected_prefixes)
    dominant_prefix = ""
    if prefix_counts:
        dominant_prefix = prefix_counts.most_common(1)[0][0]

    effective_start = max_detected + 1 if max_detected > 0 else user_start
    effective_prefix = dominant_prefix

    logger.info(
        "Bates pre-pass: %d file(s) already labeled, detected prefix=%r, "
        "auto-continuing new stamps at %d",
        len(skip_existing), effective_prefix, effective_start,
    )
    return skip_existing, effective_prefix, effective_start


@app.post("/bates")
async def bates_endpoint(
    files: List[UploadFile] = File(...),
    prefix: str = Form(""),
    start_num: int = Form(1),
    digits: int = Form(8),
    font_name: str = Form("Helvetica"),
    font_size: int = Form(12),
    margin_right: float = Form(18.0),
    margin_bottom: float = Form(18.0),
    zone: Optional[str] = Form(None), # "Bottom Left (Z1)", "Bottom Center (Z2)", "Bottom Right (Z3)"
    zone_padding: float = Form(18.0),
    color_hex: str = Form("#0000FF"),
    left_punch_margin: float = Form(0.0),
    border_all_pt: float = Form(0.0),
    diagnostics: bool = Form(False),
    font_bold: bool = Form(False),
):
    """
    Apply Bates labels to PDFs and Images.
    """
    file_pairs = []
    for f in files:
        content = await f.read()
        if f.filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Could not read '{f.filename}': it may be corrupt or not a valid ZIP.")
            del content  # free upload bytes after extraction
        else:
            file_pairs.append((f.filename, content))

    color_rgb = logic._color_from_hex(color_hex)

    if font_bold:
        font_name = "Helvetica-Bold"

    logger.info("Bates request: %d file(s)", len(file_pairs))

    # Smart pre-pass: detect files that already carry a Bates label so
    # /bates can pass them through unchanged instead of double-stamping.
    # When any file is detected, auto-continue numbering from the detected
    # max using the detected prefix — the user's start_num/prefix form
    # fields are only used when no pre-labels are found (fresh production).
    skip_existing, effective_prefix, effective_start = _detect_preexisting_bates(
        file_pairs, user_prefix=prefix, user_start=start_num,
    )

    try:
        records, last_used, zip_path, failed = await asyncio.to_thread(
            logic.walk_and_label,
            file_pairs,
            prefix=effective_prefix,
            start_num=effective_start,
            digits=digits,
            font_name=font_name,
            font_size=font_size,
            margin_right=margin_right,
            margin_bottom=margin_bottom,
            zone=zone,
            zone_padding=zone_padding,
            color_rgb=color_rgb,
            left_punch_margin=left_punch_margin,
            border_all_pt=border_all_pt,
            diagnostics=diagnostics,
            skip_existing=skip_existing,
        )

        from fastapi.responses import FileResponse
        from starlette.background import BackgroundTask

        def _cleanup(p):
            try:
                os.unlink(p)
            except Exception:
                logger.exception("Failed to delete temp zip: %s", p)

        cleanup_task = BackgroundTask(_cleanup, str(zip_path))

        single = _maybe_unwrap_single_file_path(zip_path)
        if single:
            file_bytes, file_name, media = single
            out_name = _output_name(files, "_LABELED", "." + file_name.rsplit(".", 1)[-1])
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    "X-Last-Bates-Number": str(last_used),
                    "X-Bates-Failed-Count": str(len(failed))
                },
                background=cleanup_task,
            )

        return FileResponse(
            str(zip_path),
            media_type="application/zip",
            filename=_output_name(files, "_LABELED"),
            headers={
                "X-Last-Bates-Number": str(last_used),
                "X-Bates-Failed-Count": str(len(failed))
                },
            background=cleanup_task,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 4. DISCOVERY INDEX
# -----------------------------------------------------------------------------
@app.post("/index")
async def index_endpoint(
    file: UploadFile = File(...), # Expecting a labeled ZIP
    party: str = Form("Client"),
    title_text: str = Form("CLIENT NAME - DOCUMENTS"),
    bates_metadata: Optional[str] = Form(None),
):
    """
    Generate Discovery Index Excel from a ZIP of labeled files.
    """
    content = await file.read()
    pairs = []
    rows = []
    sidecar_records: Optional[list] = None  # __bates_records.json from /bates output

    try:
        if file.filename.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                for info in zf.infolist():
                    if info.is_dir() or logic._is_mac_resource_junk(info.filename):
                        continue
                    # The sidecar is the server's authoritative record of
                    # what was stamped. Read it once and exclude from the
                    # document list so it doesn't land in the Excel.
                    if logic._is_bates_sidecar(info.filename):
                        try:
                            sidecar_records = json.loads(zf.read(info).decode("utf-8"))
                            if not isinstance(sidecar_records, list):
                                logger.warning("Bates sidecar is not a list, ignoring")
                                sidecar_records = None
                        except (json.JSONDecodeError, UnicodeDecodeError) as e:
                            logger.warning("Failed to parse bates sidecar: %s", e)
                            sidecar_records = None
                        continue
                    data = zf.read(info)
                    pairs.append((info.filename, data))

                    # Basic metadata
                    p = logic.Path(info.filename)
                    rel_dir = str(p.parent) if str(p.parent) != "." else ""
                    cat = p.parts[-2] if len(p.parts) > 1 else ""
                    rows.append({"rel_dir": rel_dir, "filename": p.name, "category": cat})
        elif file.filename.lower().endswith(".pdf"):
            pairs.append((file.filename, content))
            p = logic.Path(file.filename)
            rows.append({"rel_dir": "", "filename": p.name, "category": ""})
        else:
            raise HTTPException(status_code=400, detail="Please select a PDF or ZIP file.")
        
        df = logic.pd.DataFrame(rows)

        # Use provided Bates metadata if available, otherwise detect from files
        def _norm_meta_key(path_like: str) -> str:
            """Normalize a path for metadata lookup: forward slashes, strip leading ./."""
            s = str(path_like or "").replace("\\", "/").lstrip("./")
            return s

        def _row_meta_keys(rel_dir: str, filename: str):
            """Candidate keys to try when looking up a row in the metadata.
            Prefer full path (rel_dir/filename) but fall back to bare filename
            for backwards-compat with older plugin payloads."""
            filename = str(filename or "")
            rel_dir = str(rel_dir or "")
            if rel_dir and rel_dir != ".":
                yield _norm_meta_key(f"{rel_dir}/{filename}")
            yield _norm_meta_key(filename)

        # Priority order for Bates resolution:
        #   1. Sidecar (__bates_records.json) — authoritative, emitted by /bates
        #   2. bates_metadata form field — legacy plugin payload
        #   3. scan_pairs_for_bates — detection fallback (reads stamps from files)
        if sidecar_records is not None:
            # Build lookup from the sidecar. Each record has first_label,
            # last_label, and a path keyed by rel_dir/filename.
            side_lookup = {}
            for rec in sidecar_records:
                if not isinstance(rec, dict):
                    continue
                path = rec.get("path") or ""
                rel_dir = rec.get("rel_dir") or ""
                fname = rec.get("filename") or ""
                first_label = str(rec.get("first_label", "") or "")
                last_label = str(rec.get("last_label", "") or first_label)
                entry = (first_label, last_label)
                if path:
                    side_lookup[_norm_meta_key(path)] = entry
                if rel_dir or fname:
                    if rel_dir and rel_dir != ".":
                        side_lookup.setdefault(_norm_meta_key(f"{rel_dir}/{fname}"), entry)
                    else:
                        side_lookup.setdefault(_norm_meta_key(fname), entry)
                if fname:
                    # Filename-only fallback for single-file edge cases.
                    side_lookup.setdefault(_norm_meta_key(fname), entry)

            first_labels = []
            last_labels = []
            for _, row in df.iterrows():
                entry = None
                for k in _row_meta_keys(row.get("rel_dir", ""), row.get("filename", "")):
                    if k in side_lookup:
                        entry = side_lookup[k]
                        break
                if entry:
                    first_labels.append(entry[0])
                    last_labels.append(entry[1])
                else:
                    first_labels.append("")
                    last_labels.append("")
            df["first_label"] = first_labels
            df["last_label"] = last_labels
        elif bates_metadata:
            try:
                meta_list = json.loads(bates_metadata)
                # Build lookup keyed by full path when available, falling back
                # to bare filename. Collisions on bare filename are resolved
                # by last-write-wins for old payloads, which is the legacy
                # behavior — the path-keyed entries are what prevent the
                # duplicate-filename collision bug.
                meta_lookup = {}
                for item in meta_list:
                    name = item.get("name", "")
                    full_path = item.get("path") or item.get("fullPath") or ""
                    bates_range = item.get("batesRange", "") or ""
                    if full_path:
                        meta_lookup[_norm_meta_key(full_path)] = bates_range
                    if name:
                        # Always keep a filename-only entry as a fallback,
                        # but don't let it clobber a path-keyed entry.
                        meta_lookup.setdefault(_norm_meta_key(name), bates_range)

                first_labels = []
                last_labels = []
                for _, row in df.iterrows():
                    bates_range = ""
                    for k in _row_meta_keys(row.get("rel_dir", ""), row.get("filename", "")):
                        if k in meta_lookup:
                            bates_range = meta_lookup[k]
                            break
                    if " - " in bates_range:
                        parts = bates_range.split(" - ", 1)
                        first_labels.append(parts[0].strip())
                        last_labels.append(parts[1].strip())
                    elif bates_range:
                        first_labels.append(bates_range.strip())
                        last_labels.append(bates_range.strip())
                    else:
                        first_labels.append("")
                        last_labels.append("")

                df["first_label"] = first_labels
                df["last_label"] = last_labels
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning("Invalid bates_metadata, falling back to detection: %s", e)
                det = logic.scan_pairs_for_bates(pairs)
                if not det.empty:
                    df = df.merge(det[["rel_dir","filename","first_label","last_label"]], on=["rel_dir","filename"], how="left")
        else:
            det = logic.scan_pairs_for_bates(pairs)
            if not det.empty:
                df = df.merge(det[["rel_dir","filename","first_label","last_label"]], on=["rel_dir","filename"], how="left")

        # Prepare for Excel
        if {"first_label","last_label"}.issubset(df.columns):
            fl = df["first_label"].fillna("").astype(str)
            ll = df["last_label"].fillna("").astype(str)
            df["Bates Range"] = logic.np.where(
                (fl != "") & (ll != "") & (fl != ll),
                fl + " - " + ll,
                logic.np.where(fl != "", fl, ll)
            )
        else:
            df["Bates Range"] = ""

        df.rename(columns={"category":"Category", "filename":"Document Name/Title"}, inplace=True)
        
        df["Date Produced"] = df.apply(
            lambda r: logic._extract_date_produced_from_rel(r.get("rel_dir",""), r.get("Document Name/Title","")),
            axis=1
        )
        df["Date Produced"] = df["Date Produced"].apply(
            lambda d: d if logic.pd.notnull(d) and d != "" else datetime.today().date()
        )

        xlsx_bytes = logic.build_discovery_xlsx(
            df[["Date Produced","Document Name/Title","Category","Bates Range"]],
            party=party,
            title_text=title_text
        )

        return StreamingResponse(
            io.BytesIO(xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{_output_name([file], "_index", ".xlsx")}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 5. REDACTION
# -----------------------------------------------------------------------------
@app.post("/redact")
async def redact_endpoint(
    file: UploadFile = File(...), # ZIP or PDF
    presets: List[str] = Form([]),
    regex_patterns: Optional[str] = Form(None), # newline separated
    literal_patterns: Optional[str] = Form(None), # comma separated
    case_sensitive: bool = Form(False),
    keep_last_digits: int = Form(0),
    require_ssn_context: bool = Form(True)
):
    """
    Redact PDF or ZIP of PDFs.
    """
    content = await file.read()
    
    # Compile patterns
    try:
        patterns = logic.load_patterns(presets, regex_patterns or "", literal_patterns or "", case_sensitive)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # If single PDF, wrap in ZIP for uniform processing or handle separately?
    # Logic expects ZIP bytes for `process_zip_bytes`.
    # If it's a PDF, let's zip it in memory first to reuse `process_zip_bytes` easily,
    # or we could expose `redact_pdf_bytes` directly. 
    # Reusing `process_zip_bytes` gives us the audit report for free.
    
    input_zip_bytes = content
    if file.filename.lower().endswith(".pdf"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(file.filename, content)
        input_zip_bytes = buf.getvalue()
    elif not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be PDF or ZIP.")

    try:
        out_zip, hits, summary = logic.process_zip_bytes(
            input_zip_bytes,
            patterns,
            keep_last_digits,
            require_ssn_context=require_ssn_context
        )

        single = _maybe_unwrap_single_file(out_zip)
        if single:
            file_bytes, file_name, media = single
            out_name = _output_name([file], "_redacted", "." + file_name.rsplit(".", 1)[-1])
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    "X-Total-Hits": str(summary["total_hits"])
                }
            )

        return StreamingResponse(
            io.BytesIO(out_zip),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{_output_name([file], "_redacted")}"',
                "X-Total-Hits": str(summary["total_hits"])
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 6. OCR (Make Searchable)
# -----------------------------------------------------------------------------
@app.post("/ocr")
async def ocr_endpoint(
    files: List[UploadFile] = File(...),
):
    """
    Perform OCR on scanned PDFs to make them searchable.
    """
    # Collect files (handle ZIP extraction)
    file_pairs = []
    for f in files:
        content = await f.read()
        if f.filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Could not read '{f.filename}': it may be corrupt or not a valid ZIP.")
        else:
            file_pairs.append((f.filename, content))

    logger.info("OCR request: %d file(s)", len(file_pairs))

    try:
        async with _ocr_semaphore:
            result_pairs, ocr_failed = await asyncio.to_thread(_ocr_file_pairs, file_pairs)

        # Single file — return bare PDF/image
        if len(result_pairs) == 1:
            name, data = result_pairs[0]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            media = _SINGLE_FILE_TYPES.get(f".{ext}", "application/octet-stream")
            out_name = _output_name(files, "_searchable", "." + name.rsplit(".", 1)[-1])
            return Response(
                content=data,
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    "Content-Length": str(len(data)),
                    "X-OCR-Failed-Count": str(len(ocr_failed))
                }
            )

        # Multiple files — return ZIP
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in result_pairs:
                zout.writestr(name, data)
        zip_bytes = out_buf.getvalue()

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{_output_name(files, "_searchable")}"',
                "Content-Length": str(len(zip_bytes)),
                "X-OCR-Failed-Count": str(len(ocr_failed))
            }
        )
    except Exception as e:
        logger.exception("OCR endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


def _ocr_file_pairs(file_pairs: list):
    """Process file pairs through OCR with sidecar-aware gap-fill.

    If the input contains a ``__bates_records.json`` sidecar, gap-fill mode
    activates: files missing from the sidecar get labeled with continued
    numbering, sidecar-listed image labels are redrawn as native PDF text,
    and an updated sidecar is emitted. Otherwise OCR runs plain.
    """
    return logic.process_file_pairs(file_pairs)