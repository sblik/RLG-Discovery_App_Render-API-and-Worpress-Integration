# CLAUDE.md — SCOUT / Discovery One-Stop API

> Context file for AI assistants. Read this before touching any code.

---

## What This Project Is

A **legal document automation platform** for law firms. It is split into two parts:

1. **FastAPI backend** (`main.py` + `logic/`) — processes legal PDFs and images: unlock, organize, Bates stamp, redact, make searchable (OCR), and generate discovery indexes.
2. **WordPress plugin** (`wordpress-plugin/rlg-discovery-integration/`) — a shortcode-based frontend that lets attorneys upload files and trigger the API directly from a WordPress page.

The API is deployed on **Render** (Docker, Pro plan, 300 s timeout). The WordPress plugin calls the API directly from the browser (not through the WP server) to avoid WordPress's short request timeout.

---

## Repository Layout

```
SCOUT CODE REPOSITORY/
├── main.py                          # FastAPI app — all 6 API endpoints
├── requirements.txt                 # Python dependencies
├── packages.txt                     # System packages (libgl1 for image processing)
├── Dockerfile                       # python:3.11-slim, pre-downloads OCR models
├── render.yaml                      # Render deployment config (Docker, Pro plan)
├── PROJECT_DOCUMENTATION.md        # Human-readable API docs
├── RENDER_DEPLOYMENT_GUIDE.md      # Deployment instructions
│
├── logic/                           # Framework-independent business logic
│   ├── __init__.py                  # Re-exports everything; import `logic` from main.py
│   ├── utils.py                     # Font loading, ZIP helpers, color parsing, macOS junk filters
│   ├── pdf_unlock.py                # pikepdf-based PDF password removal
│   ├── text_extraction.py           # Native PDF text + OnnxTR OCR fallback
│   ├── bates_detection.py           # Smart Bates number detection from margin text
│   ├── bates_labeler.py             # Bates stamping via ReportLab overlay + pikepdf merge
│   ├── dates.py                     # Year/date extraction (filename → metadata → content)
│   ├── organize.py                  # Year-based folder organization
│   ├── excel.py                     # OpenPyXL discovery index spreadsheet generation
│   ├── redaction.py                 # PyMuPDF quad-redaction with OCR fallback
│   ├── ocr_engine.py                # Thread-safe OnnxTR singleton predictor
│   └── ocr_processor.py             # Full OCR pipeline with sidecar-aware gap-fill
│
├── wordpress-plugin/
│   └── rlg-discovery-integration/
│       ├── rlg-discovery-integration.php   # Main WP plugin file
│       ├── admin/settings-page.php          # WP settings menu (API URL config)
│       └── public/
│           ├── shortcodes.php               # 5 shortcodes: unlock, organize, bates, index, redact
│           └── js/
│               ├── rlg-core.js              # Global namespace, shared state
│               ├── rlg-form-handler.js      # Form submit, API calls, download handling
│               ├── rlg-file-handlers.js     # File upload, JSZip extraction
│               ├── rlg-bates-detection.js   # Client-side Bates detection (PDF.js)
│               ├── rlg-bates-preview.js     # Preview rendering
│               ├── rlg-index-preview.js     # Index table preview
│               └── rlg-ui-controls.js       # Color pickers, toggles, dropdowns
│
├── test_api.py                      # Basic API smoke tests
├── test_all_inputs.py               # Input variation tests
├── test_bates_positioning.py        # Bates label position tests
├── test_font.py                     # Font loading tests
└── create_plugin_zip.py             # Script to package the WP plugin as a .zip
```

---

## API Endpoints

| Method | Path       | Description                                      | Key Input Params                         | Output                        |
|--------|------------|--------------------------------------------------|------------------------------------------|-------------------------------|
| GET    | `/`        | Health check / endpoint list                     | —                                        | JSON                          |
| POST   | `/unlock`  | Remove PDF encryption                            | `files`, `password_mode`, `password_for_all`, `password_csv` | ZIP of unlocked PDFs |
| POST   | `/organize`| Sort files into year-named folders               | `files`, `min_year`, `max_year`, `year_policy`, `unknown_folder` | ZIP with year folders |
| POST   | `/bates`   | Apply Bates stamps to PDFs/images                | `files`, `prefix`, `start_num`, `digits`, `zone`, font/color/margin params | ZIP + `X-Last-Bates-Number` header |
| POST   | `/index`   | Generate Excel discovery index                   | `file` (ZIP), `party`, `title_text`, `bates_metadata` | `.xlsx` spreadsheet |
| POST   | `/redact`  | Redact sensitive content                         | `file`, `presets`, `regex_patterns`, `literal_patterns`, `keep_last_digits` | ZIP of redacted PDFs + `X-Total-Hits` header |
| POST   | `/ocr`     | Make PDFs/images searchable via OCR              | `files`                                  | ZIP or single PDF             |

**All endpoints accept ZIPs** as input and unwrap single-file ZIPs automatically for download (e.g., one PDF → bare PDF download, not wrapped in a ZIP).

---

## Key Design Decisions

### Bates Sidecar (`__bates_records.json`)
When `/bates` runs, it writes a `__bates_records.json` sidecar inside the output ZIP. This JSON array is the **authoritative source of truth** for what was stamped. The `/index` endpoint reads this sidecar to populate Bates ranges in the spreadsheet without re-detecting from files. The `/ocr` endpoint also reads it to perform "gap-fill" (labeling loose files that weren't in the original batch).

**Priority order in `/index`:**
1. Sidecar from ZIP (most reliable)
2. `bates_metadata` form field (legacy plugin payload)
3. `scan_pairs_for_bates()` detection (fallback)

### Bates Pre-Pass in `/bates`
Before labeling, `/bates` calls `scan_pairs_for_bates()` to detect files that already carry a Bates stamp. Those files are **passed through unchanged** (not re-stamped), and their detected range is recorded in the sidecar. New numbering continues from `max_detected + 1`. This is the "smart skip" or "continuation" behavior.

### OCR Architecture
- **Engine:** OnnxTR (no system binaries — no Tesseract, no Ghostscript)
- **Lazy singleton:** `ocr_engine.get_predictor()` uses double-checked locking to load models once
- **Eager startup:** `main.py` calls `get_predictor()` at import time so memory is claimed before the first request
- **Concurrency gate:** `_ocr_semaphore` (default `OCR_CONCURRENCY=1`) serializes OCR jobs to avoid OOM
- **DPI:** `ONNXTR_DPI` env var (default 150). Higher = better accuracy, more RAM.
- **Models:** `ONNXTR_DET_ARCH` (default `fast_tiny`) and `ONNXTR_RECO_ARCH` (default `crnn_mobilenet_v3_small`)

### Bates Label Placement
Labels are drawn using ReportLab (creates an invisible overlay PDF) merged onto the original via pikepdf's `add_overlay()`. This preserves the original PDF's structure. Zone options:
- **Bottom Right (Z3):** default, `drawRightString(page_x2 - mr, page_y1 + mb, label)`
- **Bottom Center (Z2):** `mr` = `(page_w - text_w) / 2`
- **Bottom Left (Z1):** `mr` = `page_w - pad - text_w`

All zones use `drawRightString()` with a computed `label_x` — the universal formula is `label_x = crop_x2 - effective_mr`.

### Margin-Only Bates Detection
Detection (`bates_detection.py`) intentionally restricts text search to the **bottom 12% of each page** (`_pdf_page_margin_blocks`). This eliminates false positives from body text like "TRS Participant ID: 00549327". The OCR fallback was deliberately removed from this path (commit history explains why: small margin-strip OCR was unreliable).

### ZIP Streaming for Large Files
`/bates` uses `_zip_dir_to_path()` to write the output ZIP to a **temp file on disk** rather than holding it in memory. `FileResponse` streams it to the client, then a `BackgroundTask` deletes the temp file. Other endpoints still use in-memory bytes — migration to the same approach would help for large batches.

---

## Running Locally

```bash
# 1. Python 3.11 required
python --version  # should be 3.11.x

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the dev server (auto-reload)
uvicorn main:app --reload --port 8000

# 4. Visit http://localhost:8000 — health check JSON
# 5. Interactive API docs: http://localhost:8000/docs
```

**WordPress plugin:** Set the API URL in WP Admin → Settings → RLG Discovery Integration to `http://localhost:8000`.

### Running Tests

```bash
python test_api.py           # smoke tests
python test_bates_positioning.py
python test_all_inputs.py
python test_font.py
```

Tests assume a local server is running on `http://localhost:8000`. They are not pytest-based (plain scripts).

---

## Environment Variables

| Variable             | Default                          | Purpose                                           |
|----------------------|----------------------------------|---------------------------------------------------|
| `PORT`               | `8000` (set by Render)           | uvicorn listening port                            |
| `OCR_CONCURRENCY`    | `1`                              | Max parallel OCR jobs (higher = more RAM usage)   |
| `ONNXTR_DPI`         | `150`                            | PDF render DPI for OCR                            |
| `ONNXTR_DET_ARCH`    | `fast_tiny`                      | OnnxTR detection model architecture              |
| `ONNXTR_RECO_ARCH`   | `crnn_mobilenet_v3_small`        | OnnxTR recognition model architecture            |

---

## Dependencies

### Python (requirements.txt)
| Package | Used For |
|---------|----------|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `python-multipart` | Form/file upload parsing |
| `pymupdf` (fitz) | PDF text extraction, OCR text layer insertion, redaction |
| `pikepdf` | PDF encryption/repair, Bates overlay merge |
| `reportlab` | Creating Bates label overlay PDFs |
| `Pillow` | Image processing, label drawing on images |
| `onnxtr[cpu-headless]` | Deep-learning OCR (no GPU required) |
| `pandas` / `numpy` | Bates scan DataFrames, index generation |
| `openpyxl` | Excel spreadsheet generation |
| `PyPDF2` | PDF page count fallback |
| `streamlit` | ⚠️ **UNUSED** — listed but never imported |

### System (packages.txt)
- `libgl1` — OpenGL library required by image processing libs

### JavaScript (CDN, in WordPress plugin)
- **PDF.js** — Client-side PDF rendering for preview
- **JSZip** — Client-side ZIP reading/writing

---

## Deployment (Render)

- **Runtime:** Docker (uses `Dockerfile`)
- **Plan:** Pro (required for 300 s max request timeout — large OCR batches)
- **Auto-deploy:** Triggered by `git push` to the connected branch
- **OCR models:** Pre-downloaded at Docker build time (see `Dockerfile` `RUN python -c ...`)
- **Logs:** Available in Render dashboard

When updating the WordPress plugin, run `python create_plugin_zip.py` to produce a new `.zip`, then upload via WP Admin → Plugins → Add New → Upload.

---

## Known Gotchas

1. **`streamlit` in requirements.txt** is unused; don't add Streamlit code — this project is FastAPI only.
2. **CropBox vs MediaBox:** Bates label positioning uses `cropbox` when present, `mediabox` as fallback. The overlay is sized to the MediaBox but the label is positioned relative to the CropBox visible area.
3. **Image → PDF conversion in `/bates`:** Input images are rendered onto 8.5×11 letter pages (aspect-preserved, centered). The output filename changes from `.jpg`/`.png` to `.pdf`. The sidecar records the `.pdf` name.
4. **`_format_label` with empty prefix** produces a leading space (e.g., `" 00000001"`). This is intentional for bare-number labels — the detection regex handles leading/trailing whitespace.
5. **Temp files:** `/bates` creates a temp file that survives the staging dir context. The `BackgroundTask` deletes it after the response streams. If the server crashes mid-response, temp files accumulate in `/tmp`.
6. **OCR concurrency on Render Pro:** Default `OCR_CONCURRENCY=1` is safe. Increasing it risks OOM on the 2 GB Pro plan.
7. **Multiple plugin zip files** in the repo root (`rlg-discovery-integration-*.zip`) are build artifacts — gitignore them or clean up regularly.

---

## File Conventions

- **`logic/` functions** never import from `main.py`. They accept raw bytes and return bytes. They have no FastAPI dependency.
- **Private helpers** are prefixed with `_` (e.g., `_zip_dir`, `_color_from_hex`). They are still exported via `logic/__init__.py` for use in `main.py`.
- **Sidecar key** — always `__bates_records.json` at the ZIP root. Defined as `BATES_RECORDS_SIDECAR` in `bates_labeler.py` and imported by `ocr_processor.py`.
- **Mac junk filtering** — `_is_mac_resource_junk()` is called everywhere ZIPs are read. Never skip this filter.
