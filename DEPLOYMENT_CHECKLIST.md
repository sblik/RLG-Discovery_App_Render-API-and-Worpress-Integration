# Deployment Checklist

> **Read this before merging any PR.** Steps marked ⚠️ are required — the app
> will not work correctly until they are completed in order.

---

## Current Release — Plugin v1.9.0 / API v2.1.0

### What's new in this release

| Area | Change |
|------|--------|
| **New redaction presets** | `EIN`, `CREDIT_CARD`, and `DATE_OF_BIRTH` presets added to the redact tool and pipeline redact panel |
| **SSN regex fix** | `ss#` and similar non-alphabetic label abbreviations are now correctly recognized as SSN context words (trailing `\b` → `(?!\w)`) |
| **Swagger UI fix** | Submitting multiple presets through `/docs` now works — comma-joined preset strings are split before lookup |
| **Pipeline 500 fix** | `run_id` UnboundLocalError that caused every `/pipeline/run` call to return HTTP 500 is resolved |
| **Finalize fix** | `BatesRecord.get()` AttributeError in `/pipeline/finalize` is resolved — all Bates records now flow through to the index correctly |
| **Logging** | All `logic/` modules now emit structured INFO logs; pipeline SSE events include `elapsed_ms` |
| **UI rename** | "Discovery Pipeline" → "All-in-One Processing" throughout the `[rlg_pipeline]` shortcode UI |
| **organize.py fix** | Redundant post-loop year extraction pass removed; year distribution is now logged correctly |
| **create_plugin_zip.py fix** | Script no longer crashes on macOS — uses `Path(__file__).parent` for all paths |
| **.gitignore overhaul** | Inline comments fixed, test artifacts, planning docs, and key files now excluded |

---

## ⚠️ Required Steps

### Step 1 — Push code to trigger Render auto-deploy

```bash
git push origin main
```

Render detects the push and rebuilds the Docker image automatically.
Watch the **Logs** tab on the Render dashboard — the build takes 3–6 minutes.
The service is back online when you see `Application startup complete`.

---

### Step 2 — Upload the updated WordPress plugin ⚠️

The plugin was rebuilt as `rlg-discovery-integration-1.9.0.zip` in the repo root.

1. Log in to WordPress Admin → **Plugins → Add New → Upload Plugin**
2. Choose `rlg-discovery-integration-1.9.0.zip`
3. Click **Install Now → Replace current with uploaded**
4. Activate the plugin if prompted

> **Why is this required?**
> The shortcode PHP, all JavaScript files, and the CSS were updated.
> The old plugin files cached in the browser will serve stale JS until the plugin is replaced and the WordPress cache is cleared.
> In particular, the three new redaction presets will not appear in the UI until the plugin is updated.

---

### Step 3 — Verify the All-in-One Processing page exists

The `[rlg_pipeline]` shortcode page was introduced in v1.8.0. If it already exists (from the previous release), no action is needed — the plugin update in Step 2 is sufficient to pick up the renamed heading and button.

If the page does not yet exist:

1. WordPress Admin → **Pages → Add New**
2. Title it `All-in-One Processing` (or whatever you prefer)
3. In the body, add the shortcode: `[rlg_pipeline]`
4. Publish the page
5. Add a link to it in your portal navigation menu

> **Note on the rename:** The heading inside the shortcode now reads "All-in-One Processing" and the button reads "▶ Run All-in-One Processing". If you previously titled the WordPress page "Discovery Pipeline" you may want to rename the page title for consistency, but this is cosmetic only — the shortcode itself will show the new text regardless.

---

### Step 4 — Clear the WordPress cache ⚠️

Many caching plugins (WP Rocket, W3 Total Cache, LiteSpeed Cache) will continue serving the old plugin JavaScript to returning visitors even after the plugin is updated. You must purge the cache after every plugin upload.

**WP Rocket:** Dashboard → WP Rocket → **Clear Cache**
**W3 Total Cache:** Performance → **Purge All Caches**
**LiteSpeed Cache:** LiteSpeed Cache → **Purge All**
**No caching plugin:** Skip this step — WordPress serves PHP/JS files directly without a cache layer.

If you are unsure whether a caching plugin is active: WordPress Admin → **Plugins → Installed Plugins** and look for any plugin with "cache" in its name.

---

## ✅ Verify Everything Is Working

After completing all four steps above, test the following scenarios on **ramagelawportal.com**:

### 1. All-in-One Processing rename
- Navigate to the All-in-One Processing page
- Confirm the heading reads **"All-in-One Processing"** (not "Discovery Pipeline")
- Confirm the button reads **"▶ Run All-in-One Processing"**

### 2. New redaction presets
Use `deposition_transcript.pdf` (the test document in the shared drive) or any suitable test PDF. Run it through the standalone **Redact** tool.

| Preset | Expected hits | Notes |
|--------|---------------|-------|
| **SSN** | 3 | Confirm that `ss# 301-78-4563` style entries are found — this was the bug that was fixed |
| **EIN** | 2 | Should find `XX-XXXXXXX` format numbers near labels like "EIN:" or "Federal Tax ID:" |
| **Credit Card** | 3 | Should find Visa/MC/Amex/Discover numbers with or without spaces/hyphens |
| **Date of Birth** | 2 | Should only redact dates that follow a "Date of Birth:" or "D.O.B.:" label — plain dates in the body should be untouched |

Download the redacted PDF and confirm the blacked-out boxes appear in the correct positions.

### 3. Pipeline end-to-end (regression check)
- Upload a small, unlocked PDF and click **▶ Run All-in-One Processing**
- Confirm the stepper progresses through Scan → OCR → Bates → Review
- Click **Approve & Finalize** and confirm the ZIP downloads
- Upload a password-protected PDF — confirm the password panel appears after scan

---

## ℹ️ No New Environment Variables in This Release

All existing environment variables remain unchanged.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | **Yes** | *(none)* | Must match the API Key in WordPress Settings → RLG Discovery |
| `OCR_CONCURRENCY` | No | `1` | Max parallel OCR jobs — do not raise on the 2 GB Pro plan |
| `ONNXTR_DPI` | No | `150` | OCR render DPI — higher = better accuracy, more RAM |
| `ONNXTR_DET_ARCH` | No | `fast_tiny` | OnnxTR detection model |
| `ONNXTR_RECO_ARCH` | No | `crnn_mobilenet_v3_small` | OnnxTR recognition model |
| `BATES_BLACKLIST_PREFIXES` | No | *(none)* | Comma-separated prefixes to exclude from Bates detection |

---

## Rebuilding the Plugin ZIP Locally

The `create_plugin_zip.py` script was fixed in this release and now works correctly on macOS. Use it instead of the manual `zip` command:

```bash
python3 create_plugin_zip.py
```

Run this from the repository root whenever the plugin source changes. The script uses the version number from the plugin header to name the output ZIP automatically (e.g., `rlg-discovery-integration-1.9.0.zip`).

---

## Previous Release Notes

### Plugin v1.8.0 / API v2.1.0

Required steps that were completed for that release:

- **Pipeline page created** — WordPress page with `[rlg_pipeline]` shortcode added to the portal
- **API Key confirmed** on Render and in WordPress Settings → RLG Discovery → API Key field
- **Per-file failure handling** — all endpoints updated to continue on partial batch failures
- **OCR skip** — already-searchable files detected and skipped in `/ocr` and pipeline OCR stage

### Phase 1/2/3 Improvements (Plugin v1.7.x / API v2.0.0)

Required steps that were completed for that release:

- **API Key set on Render** (`API_KEY` environment variable)
- **API Key added to WordPress** (Settings → RLG Discovery → API Key field)
- **CORS locked** to `ramagelawportal.com`
- **Streamlit removed** from `requirements.txt`
- **`.dockerignore` added** — leaner Docker builds
- **Redaction audit report** — `_redaction_audit.json` now bundled in every `/redact` output ZIP
- **Version centralized** — `version.py` is the single source of truth

If any of the above steps were not completed for a previous release, complete them now before relying on this deployment.
