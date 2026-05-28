from fastapi import Depends, FastAPI, Security, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.security import APIKeyHeader
from pathlib import PurePosixPath
from starlette.background import BackgroundTask
from typing import List, Optional
import asyncio
import csv
import io
import json
import logging
import os
import time
import uuid
import zipfile
from datetime import datetime
from typing import AsyncGenerator, Dict, Tuple

import pikepdf

from version import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# API Key Authentication
# -----------------------------------------------------------------------------
# Set the API_KEY environment variable on Render to enable auth.
# If API_KEY is not set (e.g. local dev), auth is skipped so existing
# workflows aren't broken before the key is configured.
#
# The WordPress plugin sends the key in the X-API-Key request header.
# Anyone without the correct key receives HTTP 403 Forbidden.
# -----------------------------------------------------------------------------
_API_KEY = os.environ.get("API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_api_key(key: str = Security(_api_key_header)):
    """Dependency that validates the X-API-Key header on every POST endpoint.

    Behaviour:
    - API_KEY env var not set → auth disabled (backward-compatible dev mode).
    - API_KEY set + correct key supplied → request allowed.
    - API_KEY set + wrong/missing key → HTTP 403.
    """
    if not _API_KEY:
        # Auth not configured — allow all requests (safe for local development).
        if not hasattr(_verify_api_key, "_warned"):
            logger.warning(
                "API_KEY env var is not set — API key authentication is DISABLED. "
                "Set API_KEY on Render before going live."
            )
            _verify_api_key._warned = True
        return
    if key != _API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


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
    version=__version__
)

# CORS allowed origins are read from the ALLOWED_ORIGINS env var (comma-separated)
# so staging/preview deployments can use their own WordPress domain without a code
# change. Unset -> defaults to the production origin, so live behavior is unchanged.
# Staging Render service sets ALLOWED_ORIGINS to its own WordPress origin.
_origins_env = os.environ.get("ALLOWED_ORIGINS", "").strip()
_allowed_origins = (
    [o.strip() for o in _origins_env.split(",") if o.strip()]
    or ["https://ramagelawportal.com", "https://www.ramagelawportal.com"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Last-Bates-Number",
        "X-Total-Hits",
        "X-Failed-Files",
        "X-Already-Searchable",   # OCR: count of files skipped (already had text layer)
    ],
)

_SINGLE_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

OCR_CONCURRENCY = int(os.environ.get("OCR_CONCURRENCY", "1"))
_ocr_semaphore = asyncio.Semaphore(OCR_CONCURRENCY)

def _failures_header(failures: dict) -> dict:
    """Build the X-Failed-Files response header from a failures dict.

    Returns an empty dict when there are no failures (header is omitted).
    Value is compact JSON so the WordPress plugin can parse it directly:
    e.g. '{"corrupt.pdf": "OCR failed: ValueError"}'

    ensure_ascii=True is required: HTTP header values must be Latin-1 encodable,
    so any non-ASCII filename or reason (e.g. "café.pdf") must be \\uXXXX-escaped
    or the response raises UnicodeEncodeError. JSON.parse on the client restores it.
    """
    if not failures:
        return {}
    return {"X-Failed-Files": json.dumps(failures, ensure_ascii=True)}


def _output_name(files: list, suffix: str, ext: str = ".zip") -> str:
    """Build a download filename from the first uploaded file's name + a tool suffix.

    Examples:
        _output_name(files, "_LABELED")        -> "Case_Documents_LABELED.zip"
        _output_name(files, "_index", ".xlsx")  -> "Case_Documents_index.xlsx"
    """
    raw = files[0].filename if files else ""
    stem = PurePosixPath(raw).stem or "output"
    return f"{stem}{suffix}{ext}"


def _maybe_unwrap_single_file(zip_bytes: bytes):
    """If ZIP contains one supported file, return (bytes, filename, media_type). Otherwise None."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Exclude all internal sidecars from the count so a single-document
        # output always unwraps cleanly regardless of which sidecars are present
        # (Bates records, redaction audit, pipeline report).
        entries = [
            i for i in zf.infolist()
            if not i.is_dir() and not logic._is_internal_sidecar(i.filename)
        ]
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
    with zipfile.ZipFile(str(zip_path)) as zf:
        # Exclude all internal sidecars — same reason as _maybe_unwrap_single_file.
        entries = [
            i for i in zf.infolist()
            if not i.is_dir() and not logic._is_internal_sidecar(i.filename)
        ]
        if len(entries) == 1:
            ext = entries[0].filename.rsplit(".", 1)[-1].lower() if "." in entries[0].filename else ""
            media_type = _SINGLE_FILE_TYPES.get(f".{ext}")
            if media_type:
                name = entries[0].filename.split('/')[-1]
                return zf.read(entries[0]), name, media_type
    return None

@app.get("/")
def home():
    """Health check — returns API version and available endpoints."""
    return {
        "message": "Discovery One-Stop API is running.",
        "version": __version__,
        "endpoints": [
            # Individual processing tools
            "/unlock",
            "/organize",
            "/bates",
            "/index",
            "/redact",
            "/ocr",
            # Full pipeline (scan → run → review → finalize → download)
            "/pipeline/scan",
            "/pipeline/run",
            "/pipeline/re-redact/{run_id}",
            "/pipeline/finalize/{run_id}",
            "/pipeline/download/{run_id}",
        ],
    }

# -----------------------------------------------------------------------------
# 1. UNLOCK
# -----------------------------------------------------------------------------
@app.post("/unlock", dependencies=[Depends(_verify_api_key)])
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

    total_kb = sum(len(b) for _, b in file_pairs) / 1024
    logger.info("POST /unlock: %d file(s), %.1f KB total, mode=%r",
                len(file_pairs), total_kb, password_mode)
    _t0 = time.monotonic()

    password_map = {}
    if password_csv:
        content = (await password_csv.read()).decode("utf-8", errors="replace")
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
        result_zip, failures = logic.unlock_pdfs(file_pairs, password_mode, password_for_all, password_map)
        logger.info("POST /unlock: complete in %.1f s — %d failure(s)",
                    time.monotonic() - _t0, len(failures))

        single = _maybe_unwrap_single_file(result_zip)
        if single:
            file_bytes, file_name, media = single
            out_name = _output_name(files, "_unlocked", "." + file_name.rsplit(".", 1)[-1])
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    **_failures_header(failures),
                }
            )

        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{_output_name(files, "_unlocked")}"',
                **_failures_header(failures),
            }
        )
    except HTTPException:
        raise  # Re-raise intentional 4xx (e.g. 400/422) so they aren't masked as 500
    except pikepdf.PasswordError:
        raise HTTPException(status_code=400, detail="Incorrect password for one or more files.")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="One of the uploaded files is not a valid ZIP.")
    except Exception:
        logger.exception("Unexpected error in /unlock")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")

# -----------------------------------------------------------------------------
# 2. ORGANIZE
# -----------------------------------------------------------------------------
@app.post("/organize", dependencies=[Depends(_verify_api_key)])
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
    # Collect uploaded files, unwrapping any ZIPs into individual file pairs.
    # The try block starts here so BadZipFile from a corrupted upload is caught
    # with a user-friendly 400 rather than a raw 500.
    file_pairs = []
    try:
        for f in files:
            content = await f.read()
            if f.filename.lower().endswith(".zip"):
                # Expand ZIP and skip macOS resource-fork junk files (e.g. __MACOSX/)
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            else:
                file_pairs.append((f.filename, content))

        total_kb = sum(len(b) for _, b in file_pairs) / 1024
        logger.info("POST /organize: %d file(s), %.1f KB total, policy=%r",
                    len(file_pairs), total_kb, year_policy)
        _t0 = time.monotonic()

        # Run year-based organization; returns a ZIP with files sorted into
        # subfolders named by the year extracted from each document.
        result_zip, failures = logic.organize_by_year(file_pairs, min_year, max_year, year_policy, unknown_folder)
        logger.info("POST /organize: complete in %.1f s — %d failure(s)",
                    time.monotonic() - _t0, len(failures))
        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{_output_name(files, "_organized")}"',
                **_failures_header(failures),
            }
        )
    except zipfile.BadZipFile:
        # Uploaded file claims to be a ZIP but is corrupt or not actually a ZIP.
        raise HTTPException(status_code=400, detail="One of the uploaded files is not a valid ZIP.")
    except Exception:
        # Log full traceback server-side; send a generic message to the client
        # so internal error details are never exposed in browser responses.
        logger.exception("Unexpected error in /organize")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")

# -----------------------------------------------------------------------------
# 3. BATES LABELER
# -----------------------------------------------------------------------------
# Note: _BATES_TOKEN_RE, _parse_bates_token, and _detect_preexisting_bates
# have been moved to logic/bates_detection.py (pure domain logic, no HTTP
# concerns). They are called here via logic.detect_preexisting_bates().

@app.post("/bates", dependencies=[Depends(_verify_api_key)])
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
    # Collect uploaded files, unwrapping any ZIPs into individual file pairs.
    # ZIP bytes are freed immediately after extraction to keep peak memory low.
    # The try block starts here so BadZipFile from a corrupted upload is caught early.
    file_pairs = []
    try:
        for f in files:
            content = await f.read()
            if f.filename.lower().endswith(".zip"):
                # Expand ZIP; skip macOS resource-fork junk (e.g. __MACOSX/)
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
                del content  # free upload bytes after extraction
            else:
                file_pairs.append((f.filename, content))

        if not file_pairs:
            raise HTTPException(status_code=400, detail="No supported files found in the upload.")

        color_rgb = logic._color_from_hex(color_hex)

        # Helvetica-Bold is a built-in ReportLab font; map the boolean toggle here
        # so the rest of the code works with a single font_name string.
        if font_bold:
            font_name = "Helvetica-Bold"

        total_kb = sum(len(b) for _, b in file_pairs) / 1024
        logger.info("POST /bates: %d file(s), %.1f KB total, prefix=%r, start=%d, zone=%r",
                    len(file_pairs), total_kb, prefix, start_num, zone)
        _t0 = time.monotonic()

        # Smart pre-pass: detect files that already carry a Bates label so
        # /bates can pass them through unchanged instead of double-stamping.
        # When any file is detected, auto-continue numbering from the detected
        # max using the detected prefix — the user's start_num/prefix form
        # fields are only used when no pre-labels are found (fresh production).
        skip_existing, effective_prefix, effective_start = logic.detect_preexisting_bates(
            file_pairs, user_prefix=prefix, user_start=start_num,
        )

        # Walk all files, apply Bates labels, and stream the output to a temp
        # file on disk (avoids holding the full ZIP in memory for large batches).
        # walk_and_label now returns a 4-tuple: (records, last_used, zip_path, failures).
        # failures maps filename → reason for any file that could not be labeled.
        records, last_used, zip_path, failures = await asyncio.to_thread(
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

        logger.info("POST /bates: complete in %.1f s — last_num=%d, %d failure(s)",
                    time.monotonic() - _t0, last_used, len(failures))

        # Delete the temp ZIP file from disk after the response has been streamed.
        def _cleanup(p):
            try:
                os.unlink(p)
            except Exception:
                logger.exception("Failed to delete temp zip: %s", p)

        cleanup_task = BackgroundTask(_cleanup, str(zip_path))

        # If the batch contained only one file, return it unwrapped (bare PDF/image)
        # rather than a ZIP so the browser download is cleaner.
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
                    # X-Failed-Files reports any files that couldn't be labeled.
                    # Empty dict → header is omitted entirely (see _failures_header).
                    **_failures_header(failures),
                },
                background=cleanup_task,
            )

        # Multi-file batch — stream the ZIP directly from disk via FileResponse.
        # X-Last-Bates-Number lets the WordPress plugin pre-populate the next start number.
        return FileResponse(
            str(zip_path),
            media_type="application/zip",
            filename=_output_name(files, "_LABELED"),
            headers={
                "X-Last-Bates-Number": str(last_used),
                # X-Failed-Files reports any files that couldn't be labeled.
                **_failures_header(failures),
            },
            background=cleanup_task,
        )
    except HTTPException:
        raise  # Re-raise 400s we raised intentionally above
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="One of the uploaded files is not a valid ZIP.")
    except Exception:
        logger.exception("Unexpected error in /bates")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")

# -----------------------------------------------------------------------------
# 4. DISCOVERY INDEX
# -----------------------------------------------------------------------------
@app.post("/index", dependencies=[Depends(_verify_api_key)])
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
    _t0 = time.monotonic()
    logger.info("POST /index: file=%r, %.1f KB, party=%r", file.filename, len(content) / 1024, party)

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
        logger.info("POST /index: complete in %.1f s — %d row(s), sidecar=%s",
                    time.monotonic() - _t0, len(df),
                    "yes" if sidecar_records is not None else "no")

        return StreamingResponse(
            io.BytesIO(xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{_output_name([file], "_index", ".xlsx")}"'}
        )

    except HTTPException:
        raise  # Re-raise 400s we raised intentionally (e.g. unsupported file type)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid ZIP.")
    except Exception:
        logger.exception("Unexpected error in /index")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")

# -----------------------------------------------------------------------------
# 5. REDACTION
# -----------------------------------------------------------------------------
@app.post("/redact", dependencies=[Depends(_verify_api_key)])
async def redact_endpoint(
    files: List[UploadFile] = File(...),  # one or more PDFs, ZIPs, or a mix
    presets: List[str] = Form([]),
    regex_patterns: Optional[str] = Form(None),   # newline-separated
    literal_patterns: Optional[str] = Form(None), # comma-separated
    case_sensitive: bool = Form(False),
    keep_last_digits: int = Form(0),
    require_ssn_context: bool = Form(True)
):
    """
    Redact sensitive content from one or more PDFs.

    Accepts:
      • A single PDF
      • A single ZIP of PDFs
      • Multiple PDFs uploaded together (multipart)
      • Any combination of individual PDFs and ZIPs

    All files are collected into one batch and processed together.  The output
    is a single unwrapped PDF when the batch contains exactly one file, or a
    ZIP when it contains more than one.
    """
    _t0 = time.monotonic()

    # --- Collect all (filename, bytes) pairs, unwrapping any ZIPs -----------
    file_pairs: List[Tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        if f.filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail=f"'{f.filename}' is not a valid ZIP.")
        elif f.filename.lower().endswith(".pdf"):
            file_pairs.append((f.filename, content))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"'{f.filename}' is not supported. Upload PDF or ZIP files only."
            )

    if not file_pairs:
        raise HTTPException(status_code=400, detail="No PDF files found in the upload.")

    total_kb = sum(len(b) for _, b in file_pairs) / 1024
    logger.info("POST /redact: %d file(s), %.1f KB total, presets=%r",
                len(file_pairs), total_kb, presets)

    # --- Validate patterns before doing any heavy work ----------------------
    try:
        patterns = logic.load_patterns(presets, regex_patterns or "", literal_patterns or "", case_sensitive)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # --- Wrap all collected files into one input ZIP for process_zip_bytes --
    # process_zip_bytes() is the single redaction engine for all batch sizes.
    input_buf = io.BytesIO()
    with zipfile.ZipFile(input_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in file_pairs:
            zf.writestr(fname, data)
    input_zip_bytes = input_buf.getvalue()

    try:
        out_zip, hits, summary = logic.process_zip_bytes(
            input_zip_bytes,
            patterns,
            keep_last_digits,
            require_ssn_context=require_ssn_context
        )

        failures = summary.get("failures", {})
        logger.info("POST /redact: complete in %.1f s — %d hit(s), %d failure(s)",
                    time.monotonic() - _t0, len(hits), len(failures))

        # Single file in output → return unwrapped PDF for a cleaner download.
        single = _maybe_unwrap_single_file(out_zip)
        if single:
            file_bytes, file_name, media = single
            out_name = _output_name(files, "_redacted", "." + file_name.rsplit(".", 1)[-1])
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{out_name}"',
                    "X-Total-Hits": str(summary["total_hits"]),
                    **_failures_header(failures),
                }
            )

        # Multi-file batch → return the full ZIP.
        return StreamingResponse(
            io.BytesIO(out_zip),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{_output_name(files, "_redacted")}"',
                "X-Total-Hits": str(summary["total_hits"]),
                **_failures_header(failures),
            }
        )
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid ZIP.")
    except Exception:
        logger.exception("Unexpected error in /redact")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")

# -----------------------------------------------------------------------------
# 6. OCR (Make Searchable)
# -----------------------------------------------------------------------------
@app.post("/ocr", dependencies=[Depends(_verify_api_key)])
async def ocr_endpoint(
    files: List[UploadFile] = File(...),
):
    """
    Perform OCR on scanned PDFs to make them searchable.
    """
    # Collect files (handle ZIP extraction)
    # Collect uploaded files, unwrapping any ZIPs into individual file pairs.
    # The try block starts here so BadZipFile from a corrupted upload is caught early.
    file_pairs = []
    try:
        for f in files:
            content = await f.read()
            if f.filename.lower().endswith(".zip"):
                # Expand ZIP; skip macOS resource-fork junk (e.g. __MACOSX/)
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            else:
                file_pairs.append((f.filename, content))

        if not file_pairs:
            raise HTTPException(status_code=400, detail="No supported files found in the upload.")

        total_kb = sum(len(b) for _, b in file_pairs) / 1024
        logger.info("POST /ocr: %d file(s), %.1f KB total", len(file_pairs), total_kb)
        _t0 = time.monotonic()

        # _ocr_semaphore limits concurrent OCR jobs to avoid OOM on the Render Pro plan.
        # OCR runs in a thread so it doesn't block the async event loop.
        # _ocr_file_pairs returns a 3-tuple: (result_pairs, failures, already_searchable).
        # failures          — files that failed (error). already_searchable — files
        # with existing text layers that were passed through unchanged (NOT errors).
        async with _ocr_semaphore:
            result_pairs, failures, already_searchable = await asyncio.to_thread(
                _ocr_file_pairs, file_pairs
            )

        logger.info("POST /ocr: complete in %.1f s — %d processed, %d already searchable, %d failed",
                    time.monotonic() - _t0,
                    len(result_pairs) - len(already_searchable),
                    len(already_searchable), len(failures))
        if already_searchable:
            logger.info(
                "OCR: already-searchable file(s): %s", list(already_searchable.keys()),
            )

        def _already_searchable_header(already: dict) -> dict:
            """Return X-Already-Searchable header if any files were skipped.

            Value is the integer count of files that already had a text layer.
            The WordPress plugin can surface this to the user so attorneys know
            which files were truly OCR'd vs. silently passed through because
            Apple, Preview, or another tool already made them searchable.
            """
            if not already:
                return {}
            return {"X-Already-Searchable": str(len(already))}

        # Single file — return it unwrapped (bare PDF/image) for a cleaner download.
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
                    **_failures_header(failures),
                    **_already_searchable_header(already_searchable),
                }
            )

        # Multiple files — bundle into a ZIP and return.
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
                **_failures_header(failures),
                **_already_searchable_header(already_searchable),
            }
        )
    except HTTPException:
        raise  # Re-raise 400s we raised intentionally above
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="One of the uploaded files is not a valid ZIP.")
    except Exception:
        logger.exception("Unexpected error in /ocr")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred. Please try again or contact support.")


# =============================================================================
# 7. PIPELINE  (Scan → Run → Review → Finalize → Download)
# =============================================================================
#
# The pipeline combines the individual processing steps (Unlock, OCR, Bates,
# Redact, Review, Index) into a single guided workflow with real-time progress
# reporting via Server-Sent Events (SSE).
#
# Two-phase workflow:
#   Phase 1 — POST /pipeline/scan
#              Upload files; receive scan_id + manifest JSON.
#   Phase 2 — POST /pipeline/run   (SSE)
#              Streams: Unlock → OCR → Bates → Redact → review_ready event.
#              Stream ends; server holds intermediate file state under run_id.
#   Phase 3 — (optional, repeatable) POST /pipeline/re-redact/{run_id}  (SSE)
#              Apply additional redaction patterns on top of existing pass.
#              Streams a new review_ready event when done.
#   Phase 4 — POST /pipeline/finalize/{run_id}  (SSE)
#              Streams: Index → done event with download run_id.
#   Phase 5 — GET  /pipeline/download/{run_id}
#              Returns the assembled output ZIP (one-time download).
#
# All intermediate state is held in in-memory dicts with TTLs.
# Eviction is opportunistic (called on each /pipeline/scan request).
# Server restarts clear all stores — clients must re-upload.
# =============================================================================

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

PIPELINE_SCAN_TTL   = 1800   # Staged files from /scan expire after 30 min
PIPELINE_REVIEW_TTL = 3600   # Intermediate state from /run expires after 60 min
PIPELINE_RUN_TTL    = 3600   # Completed output from /finalize expires after 60 min

# {scan_id: {"files": [(filename, bytes), ...], "expires": float}}
_scan_store: Dict[str, dict] = {}

# {run_id: {
#     "files":        [(filename, bytes), ...],  # file_pairs after last redact
#     "bates_records": [...],                    # from walk_and_label
#     "last_bates_num": int,
#     "audit_bytes":   bytes | None,             # _redaction_audit.json content
#     "report":        PipelineReport,           # accumulating through all stages
#     "party":         str,
#     "title_text":    str,
#     "expires":       float,
# }}
_review_store: Dict[str, dict] = {}

# {run_id: {"zip": bytes, "expires": float}}
_run_store: Dict[str, dict] = {}


def _pipeline_store_cleanup() -> None:
    """Evict expired entries from all three stores.

    Called opportunistically on each /pipeline/scan request to prevent
    unbounded memory growth between server restarts.
    """
    now = time.time()
    for k in [k for k, v in _scan_store.items()   if v["expires"] < now]:
        del _scan_store[k]
    for k in [k for k, v in _review_store.items() if v["expires"] < now]:
        del _review_store[k]
    for k in [k for k, v in _run_store.items()    if v["expires"] < now]:
        del _run_store[k]


def _sse(data: dict) -> str:
    """Serialize *data* as a single SSE ``data:`` line followed by two newlines.

    The browser's ``EventSource`` (or a manual ``fetch`` reader in JavaScript)
    parses the JSON value from each ``data:`` line. Two newlines signal the end
    of one event so the client receives a complete message object.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 7a. PIPELINE SCAN
# ---------------------------------------------------------------------------

@app.post("/pipeline/scan", dependencies=[Depends(_verify_api_key)])
async def pipeline_scan_endpoint(
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    """
    Pre-flight scan: inspect uploaded files before the full pipeline runs.

    Unwraps any ZIPs in the upload, runs a read-only analysis on each file
    (page count, lock status, OCR text-layer detection, memory estimate), and
    stores the file bytes in memory keyed by the returned ``scan_id``.

    The client passes ``scan_id`` back to ``/pipeline/run`` so the files do
    not need to be re-uploaded. Staged files expire after 30 minutes.

    Returns JSON:
        {
          "scan_id": "<uuid>",
          "manifest": { "total_files": N, "total_pages": N, ..., "files": [...] }
        }
    """
    # Evict stale entries before adding new ones
    _pipeline_store_cleanup()

    file_pairs: List[Tuple[str, bytes]] = []
    try:
        for f in files:
            content = await f.read()
            if f.filename.lower().endswith(".zip"):
                # Unwrap the ZIP; filter out macOS resource-fork junk (__MACOSX/ etc.)
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            file_pairs.append((info.filename, zf.read(info)))
            else:
                file_pairs.append((f.filename, content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="One of the uploaded files is not a valid ZIP.")

    if not file_pairs:
        raise HTTPException(status_code=400, detail="No supported files found in the upload.")

    total_kb = sum(len(b) for _, b in file_pairs) / 1024
    logger.info("POST /pipeline/scan: %d file(s), %.1f KB total", len(file_pairs), total_kb)
    _t0 = time.monotonic()

    # Run the scan in a thread (reads PDF metadata) so we don't block the event loop.
    manifest = await asyncio.to_thread(logic.scan_files, file_pairs)
    logger.info("POST /pipeline/scan: complete in %.1f s — %d pages total, %d locked",
                time.monotonic() - _t0, manifest.total_pages, manifest.locked_count)

    # Store the file bytes for /pipeline/run to retrieve by scan_id.
    scan_id = str(uuid.uuid4())
    _scan_store[scan_id] = {
        "files": file_pairs,
        "expires": time.time() + PIPELINE_SCAN_TTL,
    }

    return JSONResponse({"scan_id": scan_id, "manifest": manifest.to_dict()})


# ---------------------------------------------------------------------------
# 7b. PIPELINE RUN  (SSE streaming — Phase 1: Unlock → OCR → Bates → Redact)
# ---------------------------------------------------------------------------
#
# This endpoint runs the first four processing stages and then pauses,
# emitting a ``review_ready`` event. The stream ends there; the server holds
# the intermediate file state in ``_review_store`` under the run_id.
#
# The client shows the review UI. After the attorney inspects and approves:
#   • POST /pipeline/re-redact/{run_id}  — additional redaction pass (optional)
#   • POST /pipeline/finalize/{run_id}   — Index stage + final download
# ---------------------------------------------------------------------------

@app.post("/pipeline/run", dependencies=[Depends(_verify_api_key)])
async def pipeline_run_endpoint(
    # Reference to files staged by /pipeline/scan
    scan_id: str = Form(...),
    # --- Unlock stage ---
    skip_unlock: bool = Form(True),          # Skip by default if no passwords
    password_mode: str = Form("none"),        # "none" | "all" | "csv"
    password_for_all: str = Form(""),         # Single password applied to every PDF
    password_csv: str = Form(""),             # CSV text: filename,password
    # --- OCR stage ---
    skip_ocr: bool = Form(False),
    # --- Redact stage ---
    skip_redact: bool = Form(True),           # Skip by default if no patterns
    presets: List[str] = Form([]),
    regex_patterns: Optional[str] = Form(None),
    literal_patterns: Optional[str] = Form(None),
    keep_last_digits: int = Form(0),
    # --- Organize stage ---
    skip_organize: bool = Form(False),
    min_year: int = Form(1900),
    max_year: int = Form(2100),
    year_policy: str = Form("earliest"),      # "earliest" | "latest" | "filename"
    unknown_folder: str = Form("Unknown"),
    # --- Bates stage ---
    skip_bates: bool = Form(False),
    prefix: str = Form(""),
    start_num: int = Form(1),
    digits: int = Form(6),
    zone: str = Form("Z3"),
    font_name: str = Form("Helvetica"),
    font_size: float = Form(8.0),
    margin_right: float = Form(36.0),
    margin_bottom: float = Form(18.0),
    zone_padding: float = Form(4.0),
    color_hex: str = Form("#000000"),
    left_punch_margin: float = Form(0.0),
    border_all_pt: float = Form(0.0),
    # --- Index settings (forwarded to /pipeline/finalize) ---
    party: str = Form("Client"),
    title_text: str = Form("CLIENT NAME - DOCUMENTS"),
    # --- Interactive password collection (from post-scan modal) ---
    passwords_json: str = Form("{}"),         # JSON: {"filename": "password", ...}
    # --- Aggressive redaction: context-free SSN / EIN matching ---
    aggressive_redact: bool = Form(False),    # True = redact all 9-digit numbers regardless of context
    # --- Custom output ZIP filename ---
    output_filename: str = Form(""),          # e.g. "Jones_v_Marlow" → Jones_v_Marlow.zip
) -> StreamingResponse:
    """
    Phase 1 of the pipeline: Unlock → OCR → Redact → Organize → Bates → review_ready.

    Retrieves staged files from /pipeline/scan using ``scan_id``, runs each
    enabled stage in order, then emits a ``review_ready`` event and ends the
    stream.  The server saves the intermediate file state under a new run_id
    in ``_review_store`` for the attorney to inspect before finalizing.

    Stage order: Unlock → OCR → Redact → Organize → Bates

    Response: ``text/event-stream``

    SSE event types emitted:

    * ``stage_start``    — stage is now running
    * ``stage_complete`` — stage finished successfully
    * ``stage_skip``     — stage was disabled (e.g. no patterns for redact)
    * ``stage_error``    — stage encountered an error but pipeline continues
    * ``review_ready``   — all Phase-1 stages done; stream ends here

    The ``review_ready`` event payload::

        {
          "type":          "review_ready",
          "run_id":        "<uuid>",           # pass to /re-redact or /finalize
          "total_hits":    42,                 # redaction matches so far (0 if skipped)
          "hits_by_file":  {"doc.pdf": 5, ...},
          "total_files":   10,
          "bates_range":   "RLG000001 - RLG000010"  # null if Bates skipped
        }

    Next steps:
        • POST /pipeline/re-redact/{run_id}  (optional, repeatable)
        • POST /pipeline/finalize/{run_id}   (required to produce download)
    """
    # -------------------------------------------------------------------------
    # Pre-flight: resolve staged files and validate settings
    # -------------------------------------------------------------------------
    entry = _scan_store.get(scan_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=(
                "scan_id not found or expired. "
                "Please re-upload your files via /pipeline/scan."
            ),
        )

    # Generate run_id immediately so it is available for logging and the report.
    run_id = str(uuid.uuid4())

    # Take a snapshot of the staged files (list of (filename, bytes) tuples).
    file_pairs: List[Tuple[str, bytes]] = list(entry["files"])
    total_kb = sum(len(b) for _, b in file_pairs) / 1024
    logger.info(
        "POST /pipeline/run: run_id=%s, scan_id=%s, %d file(s), %.1f KB — "
        "stages: unlock=%s ocr=%s redact=%s organize=%s bates=%s",
        run_id, scan_id, len(file_pairs), total_kb,
        "skip" if skip_unlock else "run",
        "skip" if skip_ocr else "run",
        "skip" if skip_redact else "run",
        "skip" if skip_organize else "run",
        "skip" if skip_bates else "run",
    )

    # Validate redaction patterns before starting the stream so a bad pattern
    # produces an immediate HTTP 400 rather than an error event mid-stream.
    patterns = None
    if not skip_redact and (presets or regex_patterns or literal_patterns):
        try:
            patterns = logic.load_patterns(
                presets, regex_patterns or "", literal_patterns or "", False
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif not skip_redact:
        # No patterns provided — treat as skipped rather than an error.
        skip_redact = True

    # Parse Bates color; fall back to black on any parse failure.
    try:
        color_rgb = logic._color_from_hex(color_hex)
    except Exception:
        logger.warning("Invalid color_hex '%s'; defaulting to black", color_hex)
        color_rgb = (0.0, 0.0, 0.0)

    # Parse interactive passwords collected by the post-scan password modal.
    # Format: {"relative/path/to/file.pdf": "secret", ...}
    # These take priority over the form's password_mode / password_for_all fields.
    _interactive_passwords: Dict[str, str] = {}
    if passwords_json.strip() not in ("", "{}"):
        try:
            _interactive_passwords = {
                k: v for k, v in json.loads(passwords_json).items()
                if isinstance(k, str) and isinstance(v, str) and v.strip()
            }
        except (json.JSONDecodeError, ValueError, AttributeError):
            logger.warning("/pipeline/run: passwords_json could not be parsed — ignored")

    # Build the PipelineReport that accumulates across all phases.
    report = logic.PipelineReport(run_id=run_id)
    report.record_settings({
        "prefix": prefix, "start_num": start_num, "digits": digits, "zone": zone,
        "skip_unlock": skip_unlock, "skip_ocr": skip_ocr,
        "skip_redact": skip_redact, "skip_organize": skip_organize,
        "skip_bates": skip_bates, "party": party,
        "aggressive_redact": aggressive_redact,
    })

    # -------------------------------------------------------------------------
    # SSE generator — Phase 1 stages
    # -------------------------------------------------------------------------
    async def _generate() -> AsyncGenerator[str, None]:
        """Yield SSE-formatted progress events for Phase 1 (Unlock→OCR→Redact→Organize→Bates)."""
        nonlocal file_pairs

        # === PRE-FLIGHT: validate interactive passwords before any heavy work ===
        # If the post-scan modal collected per-file passwords, check them now
        # (fast — just opens PDF headers with pikepdf).  A wrong password yields
        # a password_error event and terminates the stream so the attorney can
        # correct the password without waiting through OCR.
        if _interactive_passwords and not skip_unlock:
            bad_pw_files = await asyncio.to_thread(
                logic.check_passwords, file_pairs, _interactive_passwords
            )
            if bad_pw_files:
                yield _sse({
                    "type": "password_error",
                    "bad_files": bad_pw_files,
                    "message": (
                        f"Incorrect password for {len(bad_pw_files)} file(s) — "
                        "please correct and try again."
                    ),
                })
                return

        _pipeline_t0 = time.monotonic()

        # === STAGE 1: UNLOCK =================================================
        if skip_unlock:
            for fname, _ in file_pairs:
                report.record_file_ok(fname, "unlock")
            yield _sse({"type": "stage_skip", "stage": "unlock", "label": "Unlock skipped"})
        else:
            _stage_t0 = time.monotonic()
            yield _sse({"type": "stage_start", "stage": "unlock",
                        "label": "Removing PDF passwords..."})
            report.start_stage("unlock")
            try:
                # Build combined password map.
                # Priority: interactive modal passwords > form CSV > form "all" field.
                pw_map: Dict[str, str] = {}
                pw_all_str = password_for_all.strip() if password_mode == "all" else ""
                if password_mode == "csv" and password_csv:
                    for row in csv.DictReader(io.StringIO(password_csv)):
                        fk = (row.get("filename") or "").strip()
                        pv = (row.get("password")  or "").strip()
                        if fk:
                            pw_map[fk] = pv
                # Interactive modal passwords override form CSV.
                pw_map.update(_interactive_passwords)

                unlocked_pairs: List[Tuple[str, bytes]] = []
                for fname, data in file_pairs:
                    try:
                        # Resolve the best password for this file.
                        base = os.path.basename(fname)
                        stem = os.path.splitext(base)[0]
                        file_pw = (
                            pw_map.get(fname) or pw_map.get(base) or pw_map.get(stem)
                            or pw_all_str or None
                        )
                        unlock_mode = "Single password for all" if file_pw else "none"

                        unlock_zip, _ = await asyncio.to_thread(
                            logic.unlock_pdfs,
                            [(fname, data)],
                            unlock_mode,
                            file_pw,
                            {},
                        )
                        with zipfile.ZipFile(io.BytesIO(unlock_zip)) as zf:
                            names = [n for n in zf.namelist() if not n.endswith("/")]
                            unlocked_pairs.append(
                                (fname, zf.read(names[0])) if names else (fname, data)
                            )
                        report.record_file_ok(fname, "unlock")
                    except Exception as exc:
                        logger.warning("Unlock failed for '%s': %s", fname, exc)
                        report.record_file_failure(fname, "unlock", type(exc).__name__)
                        unlocked_pairs.append((fname, data))

                file_pairs = unlocked_pairs
                report.end_stage("unlock")
                _elapsed = time.monotonic() - _stage_t0
                logger.info("Pipeline [unlock] complete in %.1f s — %d file(s)", _elapsed, len(file_pairs))
                yield _sse({"type": "stage_complete", "stage": "unlock",
                            "label": f"Unlock complete — {len(file_pairs)} file(s) processed",
                            "elapsed_ms": int(_elapsed * 1000)})
            except Exception as exc:
                logger.exception("Pipeline [unlock] stage failed in %.1f s", time.monotonic() - _stage_t0)
                report.end_stage("unlock")
                yield _sse({"type": "stage_error", "stage": "unlock",
                            "label": f"Unlock error: {type(exc).__name__} — continuing"})

        # === STAGE 2: OCR ====================================================
        if skip_ocr:
            for fname, _ in file_pairs:
                report.record_file_ok(fname, "ocr")
            yield _sse({"type": "stage_skip", "stage": "ocr", "label": "OCR skipped"})
        else:
            _stage_t0 = time.monotonic()
            yield _sse({"type": "stage_start", "stage": "ocr",
                        "label": f"Running OCR on {len(file_pairs)} file(s)..."})
            report.start_stage("ocr")
            try:
                async with _ocr_semaphore:
                    # 3-tuple: (result_pairs, failures, already_searchable)
                    ocr_result_pairs, ocr_failures, ocr_already = await asyncio.to_thread(
                        _ocr_file_pairs, file_pairs
                    )
                file_pairs = ocr_result_pairs
                report.apply_failures("ocr", ocr_failures)
                for fname, _ in file_pairs:
                    if fname not in ocr_failures:
                        report.record_file_ok(fname, "ocr")
                report.end_stage("ocr")

                # Build a human-readable summary for the SSE event so the attorney
                # can see at a glance how many files were truly processed vs. already
                # searchable (Apple-OCR'd, native PDFs, etc.).
                ocr_summary = "OCR complete"
                if ocr_already:
                    ocr_summary += (
                        f" — {len(ocr_already)} file(s) already searchable (skipped OCR)"
                    )
                if ocr_failures:
                    ocr_summary += f", {len(ocr_failures)} error(s)"

                _elapsed = time.monotonic() - _stage_t0
                logger.info("Pipeline [ocr] complete in %.1f s — %d failure(s), %d already searchable",
                            _elapsed, len(ocr_failures), len(ocr_already))
                yield _sse({"type": "stage_complete", "stage": "ocr",
                            "label": ocr_summary,
                            "failures": len(ocr_failures),
                            "already_searchable": len(ocr_already),
                            "elapsed_ms": int(_elapsed * 1000)})
            except Exception as exc:
                logger.exception("Pipeline [ocr] stage failed in %.1f s", time.monotonic() - _stage_t0)
                report.end_stage("ocr")
                yield _sse({"type": "stage_error", "stage": "ocr",
                            "label": f"OCR error: {type(exc).__name__} — continuing"})

        # === STAGE 3: REDACT =================================================
        # audit_bytes holds the _redaction_audit.json written by process_zip_bytes.
        # It is accumulated across re-redact passes and written to the final ZIP.
        audit_bytes: Optional[bytes] = None
        total_hits = 0
        hits_by_file: Dict[str, int] = {}

        if skip_redact or patterns is None:
            for fname, _ in file_pairs:
                report.record_file_ok(fname, "redact")
            yield _sse({"type": "stage_skip", "stage": "redact",
                        "label": "Redaction skipped — review before finalizing"})
        else:
            _stage_t0 = time.monotonic()
            yield _sse({"type": "stage_start", "stage": "redact",
                        "label": "Applying redactions..."})
            report.start_stage("redact")
            try:
                in_buf = io.BytesIO()
                with zipfile.ZipFile(in_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                    for fname, data in file_pairs:
                        zout.writestr(fname, data)

                out_zip, hits, summary = await asyncio.to_thread(
                    logic.process_zip_bytes,
                    in_buf.getvalue(), patterns, keep_last_digits,
                    require_ssn_context=not aggressive_redact,
                )
                total_hits = len(hits)
                redact_failures = summary.get("failures", {})
                # Build per-file hit count directly from the Hit objects returned
                # by process_zip_bytes (summary dict has no "by_file" key).
                hits_by_file: Dict[str, int] = {}
                for _h in hits:
                    hits_by_file[_h.rel_path] = hits_by_file.get(_h.rel_path, 0) + 1

                with zipfile.ZipFile(io.BytesIO(out_zip)) as zf:
                    new_pairs = []
                    for info in zf.infolist():
                        if info.is_dir() or logic._is_mac_resource_junk(info.filename):
                            continue
                        if info.filename.endswith("_redaction_audit.json"):
                            audit_bytes = zf.read(info)
                        else:
                            new_pairs.append((info.filename, zf.read(info)))
                    file_pairs = new_pairs

                report.apply_failures("redact", redact_failures)
                report.end_stage("redact")
                _elapsed = time.monotonic() - _stage_t0
                logger.info("Pipeline [redact] complete in %.1f s — %d hit(s), %d failure(s)",
                            _elapsed, total_hits, len(redact_failures))
                yield _sse({"type": "stage_complete", "stage": "redact",
                            "label": f"Redaction complete — {total_hits} match(es) found",
                            "hits": total_hits, "failures": len(redact_failures),
                            "elapsed_ms": int(_elapsed * 1000)})
            except Exception as exc:
                logger.exception("Pipeline [redact] stage failed in %.1f s", time.monotonic() - _stage_t0)
                report.end_stage("redact")
                yield _sse({"type": "stage_error", "stage": "redact",
                            "label": f"Redact error: {type(exc).__name__} — continuing"})

        # === STAGE 4: ORGANIZE ===============================================
        # Sort files into year-named folders (e.g. 2021/, 2022/, Unknown/).
        # Runs after redaction so sensitive content is already removed before
        # folder names are assigned.  The resulting folder structure carries
        # forward into Bates stamping and the final index.
        if skip_organize:
            for fname, _ in file_pairs:
                report.record_file_ok(fname, "organize")
            yield _sse({"type": "stage_skip", "stage": "organize",
                        "label": "Organize skipped"})
        else:
            _stage_t0 = time.monotonic()
            yield _sse({"type": "stage_start", "stage": "organize",
                        "label": "Organizing files into year folders..."})
            report.start_stage("organize")
            try:
                org_zip_bytes, org_failures = await asyncio.to_thread(
                    logic.organize_by_year,
                    file_pairs, min_year, max_year, year_policy, unknown_folder,
                )
                # Unpack the ZIP back into (filename, bytes) pairs so subsequent
                # stages (Bates, Index) see the new folder-prefixed filenames.
                with zipfile.ZipFile(io.BytesIO(org_zip_bytes)) as zf:
                    new_pairs = []
                    for info in zf.infolist():
                        if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                            new_pairs.append((info.filename, zf.read(info)))
                    file_pairs = new_pairs

                report.apply_failures("organize", org_failures)
                for fname, _ in file_pairs:
                    if fname not in org_failures:
                        report.record_file_ok(fname, "organize")
                report.end_stage("organize")
                _elapsed = time.monotonic() - _stage_t0
                logger.info("Pipeline [organize] complete in %.1f s — %d file(s), %d failure(s)",
                            _elapsed, len(file_pairs), len(org_failures))
                yield _sse({"type": "stage_complete", "stage": "organize",
                            "label": f"Organize complete — {len(file_pairs)} file(s) sorted",
                            "failures": len(org_failures),
                            "elapsed_ms": int(_elapsed * 1000)})
            except Exception as exc:
                logger.exception("Pipeline [organize] stage failed in %.1f s", time.monotonic() - _stage_t0)
                report.end_stage("organize")
                yield _sse({"type": "stage_error", "stage": "organize",
                            "label": f"Organize error: {type(exc).__name__} — continuing"})

        # === STAGE 5: BATES ==================================================
        bates_records: list = []
        last_bates_num: int = start_num - 1

        if skip_bates:
            for fname, _ in file_pairs:
                report.record_file_ok(fname, "bates")
            yield _sse({"type": "stage_skip", "stage": "bates",
                        "label": "Bates stamping skipped"})
        else:
            _stage_t0 = time.monotonic()
            yield _sse({"type": "stage_start", "stage": "bates",
                        "label": f"Applying Bates stamps (starting at {prefix}{start_num:0{digits}d})..."})
            report.start_stage("bates")
            zip_path = None
            try:
                # Smart pre-pass: auto-detect files already carrying Bates labels
                # so they pass through unchanged (same logic as standalone /bates).
                skip_map, eff_prefix, eff_start = await asyncio.to_thread(
                    logic.detect_preexisting_bates, file_pairs,
                    user_prefix=prefix, user_start=start_num,
                )

                records, last_used, zip_path, bates_failures = await asyncio.to_thread(
                    logic.walk_and_label,
                    file_pairs,
                    prefix=eff_prefix, start_num=eff_start, digits=digits,
                    font_name=font_name, font_size=font_size,
                    margin_right=margin_right, margin_bottom=margin_bottom,
                    zone=zone, zone_padding=zone_padding,
                    color_rgb=color_rgb, left_punch_margin=left_punch_margin,
                    border_all_pt=border_all_pt, diagnostics=False,
                    skip_existing=skip_map,
                )
                last_bates_num = last_used
                bates_records = records

                with zipfile.ZipFile(str(zip_path)) as zf:
                    new_pairs: List[Tuple[str, bytes]] = []
                    for info in zf.infolist():
                        if (not info.is_dir()
                                and not logic._is_mac_resource_junk(info.filename)
                                and not logic._is_bates_sidecar(info.filename)):
                            new_pairs.append((info.filename, zf.read(info)))
                    file_pairs = new_pairs
            finally:
                if zip_path is not None:
                    try:
                        os.unlink(str(zip_path))
                    except Exception:
                        pass

            for rec in bates_records:
                # BatesRecord is a dataclass — use attribute access, not .get()
                fpath = (
                    f"{rec.rel_dir}/{rec.filename}"
                    if rec.rel_dir and rec.rel_dir not in (".", "")
                    else rec.filename
                )
                report.record_bates(fpath, rec.first_label or "", rec.last_label or "",
                                    skipped=False)
            report.apply_failures("bates", bates_failures)
            report.end_stage("bates")
            _elapsed = time.monotonic() - _stage_t0
            logger.info("Pipeline [bates] complete in %.1f s — last_num=%d, %d failure(s)",
                        _elapsed, last_bates_num, len(bates_failures))
            yield _sse({"type": "stage_complete", "stage": "bates",
                        "label": f"Bates complete — last number: {last_bates_num}",
                        "last_num": last_bates_num, "failures": len(bates_failures),
                        "elapsed_ms": int(_elapsed * 1000)})

        # === SAVE INTERMEDIATE STATE & EMIT review_ready =====================
        # The stream ends here. The attorney reviews the results in the UI,
        # optionally calls /re-redact to catch anything missed, then calls
        # /finalize to run the Index stage and get the final download.
        _review_store[run_id] = {
            "files":             file_pairs,
            "bates_records":     bates_records,
            "last_bates_num":    last_bates_num,
            "audit_bytes":       audit_bytes,
            "report":            report,
            "party":             party,
            "title_text":        title_text,
            "aggressive_redact": aggressive_redact,
            "output_filename":   output_filename or "",
            "expires":           time.time() + PIPELINE_REVIEW_TTL,
        }

        logger.info(
            "Pipeline run_id=%s: Phase 1 complete in %.1f s — "
            "%d file(s), hits=%d, bates_range=%r",
            run_id, time.monotonic() - _pipeline_t0,
            len(file_pairs), total_hits, report.bates_range,
        )
        yield _sse({
            "type":        "review_ready",
            "run_id":      run_id,
            "label":       "Review your documents — click Approve & Finalize when ready",
            "total_hits":  total_hits,
            "hits_by_file": hits_by_file,
            "total_files": len(file_pairs),
            "bates_range": report.bates_range,
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 7c. PIPELINE RE-REDACT  (optional, repeatable SSE endpoint)
# ---------------------------------------------------------------------------

@app.post("/pipeline/re-redact/{run_id}", dependencies=[Depends(_verify_api_key)])
async def pipeline_re_redact_endpoint(
    run_id: str,
    # Additional redaction patterns to apply on top of the existing pass.
    presets: List[str] = Form([]),
    regex_patterns: Optional[str] = Form(None),
    literal_patterns: Optional[str] = Form(None),
    keep_last_digits: int = Form(0),
) -> StreamingResponse:
    """
    Apply an additional redaction pass to already-redacted files.

    The attorney calls this after reviewing the output of /pipeline/run and
    spotting items that were missed. New patterns are applied on top of the
    existing redactions — redactions are additive and cannot be removed.

    May be called multiple times with the same run_id before /finalize.
    Each call emits a new ``review_ready`` event and ends the stream.

    Response: ``text/event-stream``
    """
    review_entry = _review_store.get(run_id)
    if not review_entry:
        raise HTTPException(
            status_code=404,
            detail=(
                "run_id not found or expired. "
                "The review session may have timed out — please restart the pipeline."
            ),
        )

    if not (presets or regex_patterns or literal_patterns):
        raise HTTPException(
            status_code=400,
            detail="No redaction patterns provided. Add at least one preset or pattern.",
        )

    try:
        patterns = logic.load_patterns(
            presets, regex_patterns or "", literal_patterns or "", False
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_pairs: List[Tuple[str, bytes]] = review_entry["files"]
    report: logic.PipelineReport = review_entry["report"]
    aggressive_redact: bool = review_entry.get("aggressive_redact", False)

    async def _generate() -> AsyncGenerator[str, None]:
        nonlocal file_pairs

        yield _sse({"type": "stage_start", "stage": "redact",
                    "label": "Applying additional redactions..."})
        report.start_stage("redact")

        try:
            in_buf = io.BytesIO()
            with zipfile.ZipFile(in_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for fname, data in file_pairs:
                    zout.writestr(fname, data)

            out_zip, hits, summary = await asyncio.to_thread(
                logic.process_zip_bytes,
                in_buf.getvalue(), patterns, keep_last_digits,
                require_ssn_context=not aggressive_redact,
            )
            redact_failures = summary.get("failures", {})
            hits_by_file: Dict[str, int] = {}
            for _h in hits:
                hits_by_file[_h.rel_path] = hits_by_file.get(_h.rel_path, 0) + 1

            new_pairs: List[Tuple[str, bytes]] = []
            audit_bytes: Optional[bytes] = None
            with zipfile.ZipFile(io.BytesIO(out_zip)) as zf:
                for info in zf.infolist():
                    if info.is_dir() or logic._is_mac_resource_junk(info.filename):
                        continue
                    if info.filename.endswith("_redaction_audit.json"):
                        audit_bytes = zf.read(info)
                    else:
                        new_pairs.append((info.filename, zf.read(info)))

            # Update the review store in-place so the next call (or /finalize)
            # sees the latest redacted versions of each file.
            review_entry["files"] = new_pairs
            review_entry["audit_bytes"] = audit_bytes  # Overwrite with latest audit
            review_entry["expires"] = time.time() + PIPELINE_REVIEW_TTL  # Reset TTL

            report.apply_failures("redact", redact_failures)
            report.end_stage("redact")

            _n_hits = len(hits)
            yield _sse({"type": "stage_complete", "stage": "redact",
                        "label": f"Additional redaction complete — {_n_hits} new match(es)",
                        "hits": _n_hits, "failures": len(redact_failures)})

            yield _sse({
                "type":         "review_ready",
                "run_id":       run_id,
                "label":        "Review updated — click Approve & Finalize when ready",
                "total_hits":   _n_hits,
                "hits_by_file": hits_by_file,
                "total_files":  len(new_pairs),
                "bates_range":  report.bates_range,
            })

        except Exception as exc:
            logger.exception("Re-redact stage failed for run_id=%s", run_id)
            report.end_stage("redact")
            yield _sse({"type": "stage_error", "stage": "redact",
                        "label": f"Re-redact error: {type(exc).__name__} — review unchanged"})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 7d. PIPELINE FINALIZE  (Phase 2: Index → assemble ZIP → done)
# ---------------------------------------------------------------------------

@app.post("/pipeline/finalize/{run_id}", dependencies=[Depends(_verify_api_key)])
async def pipeline_finalize_endpoint(run_id: str) -> StreamingResponse:
    """
    Phase 2: run the Index stage and produce the final downloadable ZIP.

    Called after the attorney is satisfied with the review. Runs the Index
    stage on the current (fully redacted) file state, assembles the output
    ZIP, stores it under a new download run_id, and emits a ``done`` event.

    Response: ``text/event-stream``

    Final ``done`` event payload::

        {
          "type":             "done",
          "run_id":           "<uuid>",    # use with /pipeline/download/{run_id}
          "label":            "Pipeline complete — ready to download",
          "bates_range":      "RLG000001 - RLG000010",
          "total_files":      10,
          "fully_succeeded":  9,
          "partially_failed": 1
        }
    """
    review_entry = _review_store.get(run_id)
    if not review_entry:
        raise HTTPException(
            status_code=404,
            detail=(
                "run_id not found or expired. "
                "The review session may have timed out — please restart the pipeline."
            ),
        )

    file_pairs: List[Tuple[str, bytes]] = review_entry["files"]
    bates_records: list = review_entry["bates_records"]
    audit_bytes: Optional[bytes] = review_entry["audit_bytes"]
    report: logic.PipelineReport = review_entry["report"]
    party: str = review_entry["party"]
    title_text: str = review_entry["title_text"]
    output_filename: str = review_entry.get("output_filename", "")

    # Generate a fresh download_run_id for the final ZIP. This is distinct from
    # the run_id used by /review — the same review session produces one
    # (potentially re-downloaded) final ZIP.
    download_run_id = str(uuid.uuid4())

    logger.info("POST /pipeline/finalize: run_id=%s, %d file(s)", run_id, len(file_pairs))
    _finalize_t0 = time.monotonic()

    async def _generate() -> AsyncGenerator[str, None]:

        # === INDEX ===========================================================
        _stage_t0 = time.monotonic()
        yield _sse({"type": "stage_start", "stage": "index",
                    "label": "Generating discovery index spreadsheet..."})
        report.start_stage("index")
        index_bytes: Optional[bytes] = None
        try:
            rows = []
            for fname, _ in file_pairs:
                p = PurePosixPath(fname)
                rel_dir = str(p.parent) if str(p.parent) != "." else ""
                cat = p.parts[-2] if len(p.parts) > 1 else ""
                rows.append({"rel_dir": rel_dir, "filename": p.name, "category": cat})

            df = logic.pd.DataFrame(rows)

            if bates_records:
                side_lookup: Dict[str, Tuple[str, str]] = {}
                for rec in bates_records:
                    # BatesRecord is a dataclass — use attribute access, not .get()
                    rel_dir_r = (rec.rel_dir or "").replace("\\", "/").strip("/")
                    fname_key = rec.filename or ""
                    first = str(rec.first_label or "")
                    last  = str(rec.last_label  or first)
                    # Reconstruct path from rel_dir + filename (BatesRecord has no .path field)
                    path = (f"{rel_dir_r}/{fname_key}".lstrip("./")
                            if rel_dir_r and rel_dir_r != "."
                            else fname_key)
                    if path:
                        side_lookup[path] = (first, last)
                    if fname_key:
                        side_lookup.setdefault(fname_key, (first, last))

                first_labels, last_labels = [], []
                for _, row in df.iterrows():
                    rel_d = str(row.get("rel_dir") or "").lstrip("./")
                    fn    = str(row.get("filename") or "")
                    key   = f"{rel_d}/{fn}".lstrip("./") if rel_d else fn
                    ent   = side_lookup.get(key) or side_lookup.get(fn)
                    first_labels.append(ent[0] if ent else "")
                    last_labels.append(ent[1]  if ent else "")
                df["first_label"] = first_labels
                df["last_label"]  = last_labels

            if {"first_label", "last_label"}.issubset(df.columns):
                fl = df["first_label"].fillna("").astype(str)
                ll = df["last_label"].fillna("").astype(str)
                df["Bates Range"] = logic.np.where(
                    (fl != "") & (ll != "") & (fl != ll),
                    fl + " - " + ll,
                    logic.np.where(fl != "", fl, ll),
                )
            else:
                df["Bates Range"] = ""

            df.rename(
                columns={"category": "Category", "filename": "Document Name/Title"},
                inplace=True,
            )
            df["Date Produced"] = df.apply(
                lambda r: logic._extract_date_produced_from_rel(
                    r.get("rel_dir", ""), r.get("Document Name/Title", "")
                ),
                axis=1,
            )
            df["Date Produced"] = df["Date Produced"].apply(
                lambda d: d if logic.pd.notnull(d) and d != "" else datetime.today().date()
            )

            index_bytes = logic.build_discovery_xlsx(
                df[["Date Produced", "Document Name/Title", "Category", "Bates Range"]],
                party=party, title_text=title_text,
            )
            report.end_stage("index")
            _elapsed = time.monotonic() - _stage_t0
            logger.info("Pipeline [index] complete in %.1f s — %d row(s)", _elapsed, len(df))
            yield _sse({"type": "stage_complete", "stage": "index",
                        "label": "Discovery index generated",
                        "elapsed_ms": int(_elapsed * 1000)})
        except Exception as exc:
            logger.exception("Pipeline [index] stage failed in finalize for run_id=%s", run_id)
            report.end_stage("index")
            yield _sse({"type": "stage_error", "stage": "index",
                        "label": f"Index error: {type(exc).__name__} — skipping"})

        # === ASSEMBLE OUTPUT ZIP =============================================
        report.finish()

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for fname, data in file_pairs:
                zout.writestr(fname, data)
            if index_bytes:
                zout.writestr("discovery_index.xlsx", index_bytes)
            if audit_bytes:
                zout.writestr("_redaction_audit.json", audit_bytes)
            zout.writestr("_pipeline_report.json", report.to_json())

        # Store for download; consume the review entry to free memory.
        _run_store[download_run_id] = {
            "zip":             out_buf.getvalue(),
            "output_filename": output_filename,
            "expires":         time.time() + PIPELINE_RUN_TTL,
        }
        del _review_store[run_id]

        logger.info(
            "Pipeline finalize run_id=%s complete in %.1f s — %d file(s), "
            "%d succeeded, %d partial failures, bates_range=%r",
            run_id, time.monotonic() - _finalize_t0,
            report.total_files, report.fully_succeeded, report.partially_failed,
            report.bates_range,
        )
        yield _sse({
            "type":             "done",
            "run_id":           download_run_id,
            "label":            "Pipeline complete — ready to download",
            "bates_range":      report.bates_range,
            "total_files":      report.total_files,
            "fully_succeeded":  report.fully_succeeded,
            "partially_failed": report.partially_failed,
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 7e. PIPELINE DOWNLOAD
# ---------------------------------------------------------------------------

@app.get("/pipeline/download/{run_id}", dependencies=[Depends(_verify_api_key)])
async def pipeline_download_endpoint(run_id: str) -> Response:
    """
    Download the completed pipeline output ZIP by run_id.

    The ``run_id`` is included in the final ``done`` SSE event from
    /pipeline/finalize. Results expire after 60 minutes and are deleted from
    the server after the first successful download to free memory.

    Returns the ZIP as ``application/zip`` with a
    ``Content-Disposition: attachment`` header.
    """
    _pipeline_store_cleanup()

    entry = _run_store.get(run_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=(
                "run_id not found or expired. "
                "The result may have already been downloaded or the server was restarted."
            ),
        )

    zip_bytes = entry["zip"]
    # Build a safe download filename from the user-supplied name (if any).
    raw_name  = (entry.get("output_filename") or "").strip()
    safe_name = re.sub(r'[^\w\s\-.]', '', raw_name).strip()
    if not safe_name:
        safe_name = f"pipeline_output_{run_id[:8]}"
    if not safe_name.lower().endswith(".zip"):
        safe_name += ".zip"

    del _run_store[run_id]  # One-time download: free memory immediately
    logger.info("GET /pipeline/download: run_id=%s, %.1f KB delivered, filename=%r",
                run_id, len(zip_bytes) / 1024, safe_name)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )


# =============================================================================
# OCR helper (referenced by /ocr and /pipeline/run above)
# =============================================================================

def _ocr_file_pairs(file_pairs: list) -> tuple:
    """Process file pairs through OCR with sidecar-aware gap-fill.

    If the input contains a ``__bates_records.json`` sidecar, gap-fill mode
    activates: files missing from the sidecar get labeled with continued
    numbering, sidecar-listed image labels are redrawn as native PDF text,
    and an updated sidecar is emitted. Otherwise OCR runs plain.

    Returns:
        A 3-tuple of (result_pairs, failures, already_searchable).

        result_pairs       — list of (filename, bytes) tuples ready to zip.
        failures           — maps filename → reason for files that couldn't be
                             OCR'd (e.g. corrupted PDF, OOM on a large scan).
        already_searchable — maps filename → reason for PDFs that were passed
                             through unchanged because they already had a
                             complete text layer. These are NOT failures — they
                             are normal for Apple-OCR'd or natively-created
                             PDFs. Surface the count to the user so they know
                             which files were truly processed vs. skipped.
    """
    # process_file_pairs returns a 3-tuple: propagate all three values so
    # callers can set X-Failed-Files and X-Already-Searchable headers.
    return logic.process_file_pairs(file_pairs)