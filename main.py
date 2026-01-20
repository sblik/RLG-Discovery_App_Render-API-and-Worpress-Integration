from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from typing import List, Optional
import io
import zipfile
import json
from datetime import datetime

# Import business logic
import logic

app = FastAPI(
    title="Discovery One-Stop API",
    description="API for legal document processing: Unlock, Organize, Bates Stamp, Redact.",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/")
def home():
    return {
        "message": "Discovery One-Stop API is running.",
        "endpoints": [
            "/unlock",
            "/organize",
            "/bates",
            "/index",
            "/redact"
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
        result_zip = logic.unlock_pdfs(file_pairs, password_mode, password_for_all, password_map)
        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=unlocked_pdfs.zip"}
        )
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
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for info in zf.infolist():
                    if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                        file_pairs.append((info.filename, zf.read(info)))
        else:
            file_pairs.append((f.filename, content))

    try:
        result_zip = logic.organize_by_year(file_pairs, min_year, max_year, year_policy, unknown_folder)
        return StreamingResponse(
            io.BytesIO(result_zip),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=organized_by_year.zip"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 3. BATES LABELER
# -----------------------------------------------------------------------------
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
    diagnostics: bool = Form(False)
):
    """
    Apply Bates labels to PDFs and Images.
    """
    file_pairs = []
    for f in files:
        content = await f.read()
        if f.filename.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for info in zf.infolist():
                    if not info.is_dir() and not logic._is_mac_resource_junk(info.filename):
                        file_pairs.append((info.filename, zf.read(info)))
        else:
            file_pairs.append((f.filename, content))

    color_rgb = logic._color_from_hex(color_hex)

    try:
        records, last_used, labeled_pairs = logic.walk_and_label(
            file_pairs,
            prefix=prefix,
            start_num=start_num,
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
            diagnostics=diagnostics
        )
        
        # Create ZIP of labeled files
        zip_bytes = logic._zip_from_pairs(labeled_pairs)
        
        # We can also return the records as JSON in a header or separate endpoint, 
        # but for simplicity here we return the ZIP.
        # Ideally, we might return a multipart response with JSON + ZIP, 
        # but standard browser download expects a single stream.
        # We'll include the records as a CSV inside the ZIP? 
        # Or just return the ZIP for now as per "Swiss Army Knife" flow.
        
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=bates_labeled.zip",
                "X-Last-Bates-Number": str(last_used)
            }
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
    title_text: str = Form("CLIENT NAME - DOCUMENTS")
):
    """
    Generate Discovery Index Excel from a ZIP of labeled files.
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Input must be a ZIP file.")

    content = await file.read()
    pairs = []
    rows = []
    
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
            for info in zf.infolist():
                if info.is_dir() or logic._is_mac_resource_junk(info.filename):
                    continue
                data = zf.read(info)
                pairs.append((info.filename, data))
                
                # Basic metadata
                p = logic.Path(info.filename)
                rel_dir = str(p.parent) if str(p.parent) != "." else ""
                cat = p.parts[-2] if len(p.parts) > 1 else ""
                rows.append({"rel_dir": rel_dir, "filename": p.name, "category": cat})
        
        df = logic.pd.DataFrame(rows)
        
        # Scan for Bates
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
            headers={"Content-Disposition": "attachment; filename=discovery.xlsx"}
        )

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
        
        return StreamingResponse(
            io.BytesIO(out_zip),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=redacted_output.zip",
                "X-Total-Hits": str(summary["total_hits"])
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
