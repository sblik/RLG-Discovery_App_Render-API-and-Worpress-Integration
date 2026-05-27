# CHANGELOG — SCOUT / Discovery One-Stop API

> This file records every meaningful change to the API and WordPress plugin, in reverse-chronological order.
> Each entry explains **what** changed, **why** it changed, and **how** it was implemented at a file level.
> Written for both the attorneys who use the system and the developer who maintains it.

---

## API v2.1.0 / Plugin v1.9.0 — May 2026

This release hardens the redaction tool with three new presets, closes two silent-failure bugs in the pipeline, fixes a long-standing SSN detection edge case, adds full batch processing to the redact tool (bringing it in line with every other endpoint), improves observability across all modules, and cleans up developer tooling.

---

### Redaction Improvements

---

#### New Redaction Preset: EIN (Employer Identification Number)

**What changed:** Added an `EIN` preset to the redaction engine that detects and blacks out Employer Identification Numbers in the format `XX-XXXXXXX` (two digits, hyphen, seven digits).

**Why:** Medical records, employment files, and financial exhibits frequently contain EINs. Without a dedicated preset, attorneys had to write a custom regex pattern every time, and there was no context-guard to prevent false positives.

**How:** `logic/redaction.py` — Added the regex `\b\d{2}-\d{7}\b` to PRESETS under the key `"EIN"`. Added a companion `EIN_CONTEXT_WORDS` set containing the terms `ein`, `employer id`, `employer identification`, `federal tax id`, `fein`, and `tax id`. The context check mirrors the existing SSN guard exactly: on the text-layer path the function searches the surrounding sentence for any context word before deciding to redact; on the OCR per-word path it examines a six-word sliding window. This ensures a bare hyphenated number like a case docket number (`23-1045678`) is never accidentally redacted unless a label word appears nearby. The preset was also added to the standalone redact form, the pipeline redact panel, and the re-redact review panel in `wordpress-plugin/.../shortcodes.php`.

---

#### New Redaction Preset: Credit Card Number

**What changed:** Added a `CREDIT_CARD` preset that detects and blacks out credit card numbers for the four major networks.

**Why:** Exhibits in collection cases, billing disputes, and consumer protection matters often contain payment card numbers. No compliant document should leave these exposed in production.

**How:** `logic/redaction.py` — Added five regex patterns under the key `"CREDIT_CARD"` in PRESETS:
- Visa: `\b4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b`
- Mastercard (legacy 51–55 BIN range): `\b5[1-5]\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b`
- Mastercard (2017+ 2221–2720 BIN range): `\b2(?:2[2-9]\d|[3-6]\d{2}|7[01]\d|720)[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b`
- American Express: `\b3[47]\d{2}[\s\-]?\d{6}[\s\-]?\d{5}\b`
- Discover: `\b(?:6011|65\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b`

No context-word guard was applied. Credit card number patterns are structurally specific enough (16 digits in a BIN-constrained range, often space- or hyphen-delimited in groups) that false positives are negligible in practice. The preset was added to all three UI surfaces in `shortcodes.php`.

---

#### New Redaction Preset: Date of Birth (labeled format only)

**What changed:** Added a `DATE_OF_BIRTH` preset that redacts a date only when it is directly preceded by a recognized label such as "Date of Birth:", "D.O.B.:", or "born on".

**Why:** Deposition transcripts and medical records contain dozens or hundreds of plain dates (hearing dates, treatment dates, filing dates) that must not be redacted. A naive "redact all dates" approach would be catastrophic. The labeled-only approach is intentional: if the document does not explicitly call something a date of birth, the preset leaves it alone.

**How:** `logic/redaction.py` — Added two patterns under the key `"DATE_OF_BIRTH"` in PRESETS:
- `(?i)(?:date of birth|d\.o\.b\.|dob|born on)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})`
- `(?i)(?:date of birth|d\.o\.b\.|dob|born on)[:\s]+(\w+ \d{1,2},?\s+\d{4})`

Each pattern uses a capturing group for the date portion only — the label itself is not blacked out, preserving document readability. The preset was added to all three UI surfaces in `shortcodes.php`.

---

#### Bug Fix: SSN Context-Word Regex False Negative (`ss#` not matched)

**What changed:** Fixed a regex bug that caused `ss#` and similar non-alphabetic label abbreviations to be silently ignored when deciding whether a Social Security Number had a context label.

**Why:** `SSN_CONTEXT_WORDS` used a trailing `\b` word-boundary anchor. The `\b` assertion requires a transition between a word character (`\w`) and a non-word character. The `#` character is itself a non-word character, so there is no word boundary between `#` and the space that follows it — the anchor never matched. The practical result: a document line like `ss# 301-78-4563` would not trigger the context check, so the SSN would not be redacted even though the label was clearly present. This was a latent correctness bug that would have caused compliance failures on any document using the `ss#` abbreviation.

**How:** `logic/redaction.py` — Changed the trailing `\b` in the `SSN_CONTEXT_WORDS` compiled regex to `(?!\w)` (a negative lookahead asserting "not followed by a word character"). This correctly matches:
- `ss#` followed by a space or end of string
- `SSN:` followed by a colon
- `social security number` followed by a space

...while still blocking false matches on words like `bassist` (the leading `\b` on the pattern still applies). The fix is a one-character-class change but its effect is material to correctness.

---

#### Bug Fix: Swagger UI Sends Comma-Joined Preset Names

**What changed:** Fixed a bug where submitting multiple redaction presets through the Swagger UI `/docs` interface returned zero redactions.

**Why:** FastAPI's interactive Swagger UI serializes multiple values for a `List[str]` form field by joining them with a comma into a single string — it sends `"SSN,EIN"` instead of two separate form values `["SSN", "EIN"]`. The `load_patterns()` function was looking up that whole joined string as a single key in the PRESETS dictionary, finding nothing, and silently returning zero patterns. Attorneys would see "0 hits" with no error message. This only affected the Swagger UI; the WordPress plugin sends individual form values correctly and was not affected.

**How:** `logic/redaction.py`, inside `load_patterns()` — Added a `re.split(r"\s*,\s*", key.strip())` call inside the loop that iterates over submitted preset keys. Each submitted string is split on commas before the PRESETS lookup. If a key has no comma (the normal case from the plugin), the split returns a single-element list and behavior is unchanged.

---

### Pipeline Bug Fixes

---

#### Bug Fix: `run_id` UnboundLocalError Crashed Every Pipeline Run

**What changed:** Fixed a Python `UnboundLocalError` that caused every call to `POST /pipeline/run` to return HTTP 500 before the SSE stream started.

**Why:** A `logger.info(...)` call near the top of `pipeline_run_endpoint` referenced the variable `run_id`. Python's scoping rules treat any variable that is assigned anywhere in a function as local to that function — even if the assignment appears 40 lines later. Because `run_id = str(uuid.uuid4())` appeared after the logger call, Python saw the early reference as a use-before-assignment and raised `UnboundLocalError`. The error happened before any SSE event was emitted, so clients received a generic 500 with no diagnostic information. This bug would have blocked all pipeline use since its introduction.

**How:** `main.py`, in `pipeline_run_endpoint` — Moved `run_id = str(uuid.uuid4())` to immediately after the `file_pairs` snapshot variable, before the first logger call. No logic changed; only the ordering of the variable declaration.

---

#### Bug Fix: `BatesRecord` Attribute Access in `/pipeline/finalize`

**What changed:** Fixed an `AttributeError` that caused every pipeline finalize call containing Bates records to fail at the index-building stage.

**Why:** `BatesRecord` is a Python `dataclass`. Dataclass instances are not dictionaries and do not have a `.get()` method — that method exists on `dict` objects. Code in the index-building section of `/pipeline/finalize` was calling `rec.get("path")`, `rec.get("filename")`, `rec.get("first_label")`, and `rec.get("last_label")` on `BatesRecord` instances. Every such call raised `AttributeError: 'BatesRecord' object has no attribute 'get'`. This silently broke the index step for all finalized pipelines that had applied Bates stamps.

**How:** `main.py`, in the `/pipeline/finalize` endpoint — Replaced all `.get("field")` calls with direct attribute access: `rec.rel_dir`, `rec.filename`, `rec.first_label`, `rec.last_label`. The path string (which was previously fetched as `rec.get("path")`) was reconstructed from `rec.rel_dir` and `rec.filename` since `BatesRecord` has no `.path` attribute.

---

### Logging and Observability

---

#### Comprehensive Logging Added Across All Modules

**What changed:** Every `logic/` module now has a module-level Python logger. All significant processing operations log at INFO level. All pipeline SSE `stage_complete` events now include an `elapsed_ms` field.

**Why:** Render's log output was showing only uvicorn access lines (`POST /bates HTTP/1.1 200`). There was no visibility into what happened inside a request — which files were processed, how long OCR took, why a stage was slow, or what error caused an OOM restart. Diagnosing any production issue required deploying a debug build. The new logging makes the standard Render log stream useful for routine monitoring.

**How:** The following files were updated to add `logger = logging.getLogger(__name__)` at module level and structured `logger.info()` / `logger.warning()` calls at key execution points:
- `logic/redaction.py` — logs file count, pattern count, hit count, elapsed time per file
- `logic/organize.py` — logs file count, year distribution on completion (see also bug fix below)
- `logic/excel.py` — logs row count, sheet name, elapsed time
- `logic/ocr_processor.py` — logs files processed, pages processed, files skipped (already searchable), elapsed time
- `logic/pdf_unlock.py` — logs attempt count, success count, failure list
- `logic/text_extraction.py` — logs which extraction path was taken (native text vs. OCR fallback), word count
- `main.py` — added `time.perf_counter()` timing around every endpoint's core logic and around each pipeline stage; SSE `stage_complete` events gained `"elapsed_ms"` in their JSON payload

---

### New Pipeline Infrastructure Modules

---

#### New Module: `logic/pipeline_report.py`

**What changed:** Added a new module containing the `PipelineReport` dataclass that accumulates results across all pipeline phases and serializes to JSON.

**Why:** Before this change, pipeline output ZIPs had no machine-readable summary of what was done — attorneys and downstream systems had to infer results from filenames. The `_pipeline_report.json` sidecar bundled in every pipeline ZIP now provides a structured record of settings used, per-file outcomes, stage timings, and the final Bates range, suitable for logging or audit purposes.

**How:** `logic/pipeline_report.py` (new file) — Defines `PipelineReport` as a `@dataclass` with fields for `settings` (dict), `files` (list of per-file result dicts), `stage_timings` (dict of stage-name → elapsed ms), and `bates_range` (first label, last label). Exposes a `.to_json()` method. The report is instantiated at the start of `/pipeline/run`, populated at each stage, and written as `_pipeline_report.json` into the output ZIP at finalization in `main.py`.

---

#### New Module: `logic/pipeline_scan.py`

**What changed:** Added a new module containing the `scan_files()` function that inspects uploaded files without modifying them.

**Why:** The pipeline's scan step needed to detect locked PDFs (so the password panel can appear before any processing begins), identify files that are already searchable (so OCR can skip them), and estimate memory footprint (so the API can warn about unusually large batches). Putting this logic in a separate module keeps `main.py` clean and makes the scan behavior independently testable.

**How:** `logic/pipeline_scan.py` (new file) — `scan_files()` accepts a list of `(filename, bytes)` pairs. For each file it uses `pikepdf` to check lock status, `pymupdf` to check for an existing text layer, and page-count × DPI math to estimate peak OCR memory. Returns a list of `FileScanResult` dicts consumed by `main.py`'s `/pipeline/scan` endpoint and surfaced to the browser before any processing starts.

---

### Batch Processing

---

#### Fix: `/redact` Now Accepts Multiple Files Directly

**What changed:** The `/redact` endpoint now accepts multiple files in a single upload — individual PDFs, a ZIP, or any mix of both — matching the batch behaviour already present in every other processing endpoint (`/unlock`, `/organize`, `/bates`, `/ocr`).

**Why:** `/redact` was the only tool that required attorneys to manually ZIP files before uploading a batch. Every other tool accepted multiple files through a single form submission. This inconsistency meant attorneys had to use a different workflow for redaction, and it prevented the WordPress form from showing a standard multi-file picker. Any document submitted to the redact form was inherently single-file unless the user zipped it first.

**How:**
- `main.py` — Changed the endpoint parameter from `file: UploadFile` (singular) to `files: List[UploadFile]`. Added the same ZIP-unwrapping loop used by all other endpoints: each uploaded file is read, ZIPs are unwrapped and their contents collected, bare PDFs are added directly. All collected `(filename, bytes)` pairs are then assembled into a single in-memory ZIP and passed to `process_zip_bytes()` — the existing batch redaction engine that was already doing the right thing.
- `wordpress-plugin/.../shortcodes.php` — Changed the redact form file input from `name="file"` (no `multiple`) to `name="files" multiple`, making the file picker behave identically to the unlock, organize, bates, and OCR tools.
- No changes to `rlg-form-handler.js` — `new FormData(form)` automatically serialises a multi-file input correctly.

---

#### Fix: Single-File Output Now Unwraps Correctly When Audit Sidecar Is Present

**What changed:** When a single PDF is uploaded to `/redact` (or any endpoint), the response is now always a bare PDF download rather than a ZIP. Previously, a single-file redact job returned a ZIP because the redaction audit file (`_redaction_audit.json`) was being counted as a second output file.

**Why:** The `_maybe_unwrap_single_file()` helper — used by all endpoints to decide whether to return a bare file or a ZIP — excluded the Bates sidecar (`__bates_records.json`) from its file count but did not exclude `_redaction_audit.json` or `_pipeline_report.json`. As a result, a single redacted PDF always had two entries in the output ZIP (the PDF plus the audit file), so the helper always concluded the output was multi-file and returned a ZIP instead of a clean PDF download.

**How:**
- `logic/utils.py` — Added `_is_internal_sidecar(path_str)`, a new helper that returns `True` for any of the three known sidecar files: `__bates_records.json`, `_redaction_audit.json`, and `_pipeline_report.json`. This replaces the narrower `_is_bates_sidecar()` check that was used in the unwrap logic.
- `logic/__init__.py` — Exported `_is_internal_sidecar` so `main.py` can call it.
- `main.py` — Updated both `_maybe_unwrap_single_file()` and `_maybe_unwrap_single_file_path()` to filter on `_is_internal_sidecar` instead of `_is_bates_sidecar`. Single-file output now unwraps to a bare PDF regardless of which sidecars are present.

---

### Other Fixes and Housekeeping

---

#### Bug Fix: `organize.py` Redundant Post-Loop Year Extraction

**What changed:** Removed a redundant second pass over files after the main organization loop, and replaced it with an inline `Counter` that is incremented during the main loop.

**Why:** The original code called `extract_year_cascading()` again in a summary loop after all files had already been organized, passing empty or stale bytes. This was wasted CPU on every `/organize` call. More importantly, the summary pass obscured the actual year→file-count distribution that is useful to log.

**How:** `logic/organize.py` — Removed the post-loop summary pass. Added a `collections.Counter` that is incremented as each file is processed in the main loop. After the loop completes, `logger.info("organize complete: %s", dict(year_counter))` logs the full distribution (e.g., `{"2021": 14, "2022": 8, "unknown": 2}`).

---

#### Fix: `create_plugin_zip.py` Now Works on macOS

**What changed:** Rewrote the plugin packaging script to use relative paths derived from the script's own location, making it cross-platform.

**Why:** The script contained a hardcoded Windows path (`c:\Work\...`) that caused an immediate crash on macOS. Any developer on macOS (the law firm's machines) could not use the script and had to resort to a manual `zip` command, which risked accidentally including `.DS_Store` files or other junk.

**How:** `create_plugin_zip.py` — Replaced all hardcoded path strings with `Path(__file__).parent`-relative paths. The script now correctly locates the plugin directory and output ZIP path regardless of operating system or where the repository is cloned.

---

#### Overhaul: `.gitignore`

**What changed:** Fixed broken ignore rules and expanded coverage to prevent sensitive files, test artifacts, and planning documents from being committed.

**Why:** Git does not support inline comments (a `#` after a pattern is treated as part of the pattern, not a comment). Several rules in the original `.gitignore` had inline `#` comments, meaning those patterns were never actually applied. Additionally, several categories of file that should never be committed — test documents, private key files, planning notes, and VS Code workspace files — were not covered.

**How:** `.gitignore` — Changes made:
- **Fixed inline comments:** Moved all `# ...` annotations to their own lines above the patterns they describe.
- **Added `test_documents/`** and all `test_*.py` scripts (test documents may contain confidential client data).
- **Added planning docs:** `AWS_MIGRATION_PLAN.md`, `COST_ANALYSIS.md`, `IMPROVEMENTS.md`, `SCOUT_Improvement_plan.txt`.
- **Added `.vscode/`**, `*.key`, `*.pem`, `secrets.json`.
- **Narrowed plugin ZIP glob** from `*.zip` (too broad — would ignore any ZIP in the repo) to `rlg-discovery-integration*.zip` and `rlg-discovery-plugin*.zip`.

---

#### UI Rename: "Discovery Pipeline" → "All-in-One Processing"

**What changed:** The `[rlg_pipeline]` shortcode heading and its run button now read "All-in-One Processing" instead of "Discovery Pipeline".

**Why:** "Pipeline" is a software engineering term unfamiliar to attorneys and legal staff. "All-in-One Processing" immediately communicates that the tool handles every step in a single session, which is the value proposition attorneys actually care about.

**How:**
- `wordpress-plugin/.../shortcodes.php` — Updated the `<h3>` heading text and the submit button label for the `[rlg_pipeline]` shortcode.
- `wordpress-plugin/.../js/rlg-pipeline.js` — Updated the button reset text that is restored after pipeline completion.

---

#### Plugin Version Bump: 1.8.0 → 1.9.0

**What changed:** Plugin header version updated to 1.9.0.

**How:** `wordpress-plugin/rlg-discovery-integration/rlg-discovery-integration.php` — `Version:` header field incremented.

---

---

## API v2.1.0 / Plugin v1.8.0 — (Previous Release)

This release introduced the pipeline tool, hardened all endpoints against partial-batch failures, improved deployment hygiene, and established API authentication.

---

#### New: `[rlg_pipeline]` All-in-One Processing Shortcode

Added the `[rlg_pipeline]` WordPress shortcode that chains Unlock → Scan → OCR → Bates → Redact → Review → Index into a single guided session with a real-time progress stepper. Attorneys upload once and step through the entire discovery workflow without switching between separate tools. Each stage can be enabled or disabled with a toggle switch. A scan step runs first to detect locked files and prompt for passwords inline, so the separate Unlock tool is only needed for standalone unlock jobs.

---

#### New: Per-File Failure Handling with `X-Failed-Files` Header

All endpoints (`/unlock`, `/organize`, `/bates`, `/ocr`, `/redact`, `/index`) now continue processing the remaining files in a batch when one file encounters an error, rather than aborting the entire request. Failed files are reported in the `X-Failed-Files` response header as a JSON array of `{filename, error}` objects. The WordPress plugin reads this header and displays a warning list so attorneys know exactly which files need attention without having to re-upload the entire batch.

---

#### Performance: ZIP Streaming for `/bates`

The `/bates` endpoint previously assembled the entire output ZIP in memory before sending it. For large batches (hundreds of PDFs), this was the primary cause of OOM crashes on Render's 2 GB Pro plan. The endpoint now writes the ZIP to a temporary file on disk using `_zip_dir_to_path()`, streams it to the client via `FileResponse`, and deletes the temp file in a `BackgroundTask` after the response completes. Peak memory usage is cut roughly in half for large Bates jobs.

---

#### Housekeeping: `version.py` Single Source of Truth

Introduced `version.py` containing `API_VERSION = "2.1.0"`. All version strings in `main.py` response bodies and headers now import from this module. Previously the version was duplicated in multiple places and could drift out of sync.

---

#### Security: API Key Authentication and CORS Lockdown

Added `API_KEY` environment variable enforcement. All non-health-check endpoints require an `X-API-Key` header matching the configured value. Unauthenticated requests return HTTP 403. CORS origin policy was tightened to `ramagelawportal.com` only. The WordPress plugin's Settings page was updated with an API Key field to store the key in the WP database and inject it into every API request.

---

#### Housekeeping: `.dockerignore` Added

Added `.dockerignore` to exclude test scripts, test documents, markdown planning files, and local virtual environments from the Docker build context. This reduces build upload size and prevents accidental inclusion of confidential test documents in the production image.

---

#### Feature: OCR Already-Searchable Detection and Skip

The `/ocr` endpoint and pipeline OCR stage now check each PDF for an existing text layer before running OCR. Files that Apple Preview, Adobe Acrobat, or another tool have already made searchable are passed through unchanged. The log message clearly states how many files were skipped and why. This prevents double-OCR artifacts and saves significant processing time on batches that are partially or fully searchable.

---

*For releases prior to v1.8.0 see git history (`git log --oneline`).*
