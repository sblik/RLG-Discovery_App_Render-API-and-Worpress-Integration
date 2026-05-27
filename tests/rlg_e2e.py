"""End-to-end test of Joseph's v1.9.0 features against the merged app.

Drives the real FastAPI app in-process via TestClient (full middleware,
routing, real OCR/redaction/bates logic, shared pipeline state).
Run from the worktree:  ./.venv/bin/python /tmp/rlg_e2e.py
"""
import io, json, zipfile, sys
import pikepdf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PIL import Image, ImageDraw

from fastapi.testclient import TestClient
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main

client = TestClient(main.app)
results = []  # (feature, ok, detail)

def record(feature, ok, detail=""):
    results.append((feature, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {feature} :: {detail}")

# ---------------------------------------------------------------- fixtures
def text_pdf(lines, pages=1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for _ in range(pages):
        y = 720
        for ln in lines:
            c.drawString(72, y, ln); y -= 24
        c.showPage()
    c.save()
    return buf.getvalue()

def locked_pdf(password, lines=("Confidential.",)) -> bytes:
    plain = text_pdf(list(lines))
    pdf = pikepdf.open(io.BytesIO(plain))
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(user=password, owner=password))
    return out.getvalue()

def image_bytes(text="HELLO OCR 12345") -> bytes:
    img = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(img).text((20, 80), text, fill="black")
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

SENSITIVE = [
    "SSN: 123-45-6789",
    "ss# 301-78-4563",
    "EIN: 12-3456789",
    "Credit Card: 4111 1111 1111 1111",
    "Date of Birth: 01/15/1980",
    "Hearing date 03/04/2021 (control - should NOT redact)",
]

def zip_names(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return z.namelist()

# ---------------------------------------------------------------- 0. health
try:
    r = client.get("/")
    record("health GET /", r.status_code == 200 and "version" in r.json(),
           f"HTTP {r.status_code}, version={r.json().get('version')}")
except Exception as e:
    record("health GET /", False, repr(e))

# ---------------------------------------------------------------- 1. redact all presets + ss# fix
try:
    pdf = text_pdf(SENSITIVE)
    r = client.post("/redact",
        files=[("files", ("doc.pdf", pdf, "application/pdf"))],
        data={"presets": ["SSN", "EIN", "Credit Card", "Date of Birth"],
              "require_ssn_context": "true"})
    hits = int(r.headers.get("X-Total-Hits", "-1"))
    ctype = r.headers.get("content-type", "")
    ok = r.status_code == 200 and hits >= 5 and "application/pdf" in ctype
    record("redact: all presets (SSN/EIN/CC/DOB)", ok,
           f"HTTP {r.status_code}, X-Total-Hits={hits} (expect>=5), single-file unwrap ctype={ctype.split(';')[0]}")
except Exception as e:
    record("redact: all presets", False, repr(e))

# ---------------------------------------------------------------- 2. ss# SSN context fix isolated
try:
    pdf = text_pdf(["SSN: 123-45-6789", "ss# 301-78-4563"])
    r = client.post("/redact",
        files=[("files", ("ssn.pdf", pdf, "application/pdf"))],
        data={"presets": ["SSN"], "require_ssn_context": "true"})
    hits = int(r.headers.get("X-Total-Hits", "-1"))
    # Without the ss# fix only the "SSN:" line redacts (1 hit); fix -> both (2).
    record("redact: ss# context fix", r.status_code == 200 and hits >= 2,
           f"X-Total-Hits={hits} (expect 2: 'SSN:' + 'ss#'); proves (?!\\w) fix")
except Exception as e:
    record("redact: ss# fix", False, repr(e))

# ---------------------------------------------------------------- 3. redact batch (multi-file, no zip)
try:
    r = client.post("/redact",
        files=[("files", ("a.pdf", text_pdf(["SSN: 123-45-6789"]), "application/pdf")),
               ("files", ("b.pdf", text_pdf(["EIN: 12-3456789"]), "application/pdf"))],
        data={"presets": ["SSN", "EIN"]})
    is_zip = "application/zip" in r.headers.get("content-type", "")
    names = zip_names(r.content) if is_zip else []
    pdfs = [n for n in names if n.endswith(".pdf")]
    record("redact: batch multi-file -> zip", r.status_code == 200 and is_zip and len(pdfs) == 2,
           f"HTTP {r.status_code}, zip pdfs={pdfs}")
except Exception as e:
    record("redact: batch", False, repr(e))

# ---------------------------------------------------------------- 4. unlock correct password
try:
    lp = locked_pdf("secret123")
    r = client.post("/unlock",
        files=[("files", ("locked.pdf", lp, "application/pdf"))],
        data={"password_mode": "Single password for all", "password_for_all": "secret123"})
    out_ok = False
    if r.status_code == 200:
        try:
            pikepdf.open(io.BytesIO(r.content))  # opens w/o password => unlocked
            out_ok = True
        except Exception:
            out_ok = False
    record("unlock: correct password", out_ok,
           f"HTTP {r.status_code}, output opens without password={out_ok}")
except Exception as e:
    record("unlock: correct password", False, repr(e))

# ---------------------------------------------------------------- 5. unlock failure -> X-Failed-Files
try:
    lp = locked_pdf("rightpw")
    r = client.post("/unlock",
        files=[("files", ("locked.pdf", lp, "application/pdf")),
               ("files", ("plain.pdf", text_pdf(["hello"]), "application/pdf"))],
        data={"password_mode": "Single password for all", "password_for_all": "WRONGpw"})
    xff = r.headers.get("X-Failed-Files", "")
    parsed = json.loads(xff) if xff else {}
    record("unlock: failure reporting (X-Failed-Files)",
           r.status_code == 200 and "locked.pdf" in parsed,
           f"HTTP {r.status_code}, X-Failed-Files={xff or '(absent)'}")
except Exception as e:
    record("unlock: failure reporting", False, repr(e))

# --------------------------------------- 5b. non-ASCII filename failure (header safety)
try:
    # ASCII first file -> ASCII Content-Disposition; non-ASCII *failed* file
    # exercises X-Failed-Files JSON encoding (the ensure_ascii fix).
    r = client.post("/unlock",
        files=[("files", ("doc.pdf", text_pdf(["plain"]), "application/pdf")),
               ("files", ("café_döcument.pdf", locked_pdf("rightpw"), "application/pdf"))],
        data={"password_mode": "Single password for all", "password_for_all": "WRONGpw"})
    xff = r.headers.get("X-Failed-Files", "")
    parsed = json.loads(xff) if xff else {}
    ok = r.status_code == 200 and any("caf" in k for k in parsed)
    record("X-Failed-Files: non-ASCII filename (header safety)", ok,
           f"HTTP {r.status_code} (was 500 before ensure_ascii fix), keys={list(parsed)}")
except Exception as e:
    record("X-Failed-Files: non-ASCII filename", False, repr(e))

# ---------------------------------------------------------------- 6. OCR already-searchable skip
try:
    pdf = text_pdf(["This PDF already has a text layer."])
    r = client.post("/ocr", files=[("files", ("searchable.pdf", pdf, "application/pdf"))])
    xas = r.headers.get("X-Already-Searchable", "")
    record("ocr: already-searchable skip", r.status_code == 200 and xas not in ("", None),
           f"HTTP {r.status_code}, X-Already-Searchable={xas or '(absent)'}")
except Exception as e:
    record("ocr: already-searchable skip", False, repr(e))

# ---------------------------------------------------------------- 7. OCR real image (no crash)
try:
    r = client.post("/ocr", files=[("files", ("scan.png", image_bytes(), "image/png"))])
    ctype = r.headers.get("content-type", "")
    record("ocr: image -> searchable (no crash)",
           r.status_code == 200 and ("pdf" in ctype or "zip" in ctype),
           f"HTTP {r.status_code}, ctype={ctype.split(';')[0]}")
except Exception as e:
    record("ocr: image", False, repr(e))

# ---------------------------------------------------------------- 8. organize by year
try:
    r = client.post("/organize",
        files=[("files", ("invoice_2021.pdf", text_pdf(["Dated January 5, 2021"]), "application/pdf")),
               ("files", ("invoice_2022.pdf", text_pdf(["Dated March 9, 2022"]), "application/pdf"))],
        data={})
    names = zip_names(r.content) if r.status_code == 200 else []
    has_years = any("2021" in n for n in names) and any("2022" in n for n in names)
    record("organize: by year", r.status_code == 200 and has_years,
           f"HTTP {r.status_code}, entries={names}")
except Exception as e:
    record("organize: by year", False, repr(e))

# ---------------------------------------------------------------- 9. bates + 10. index
labeled_zip = None
try:
    r = client.post("/bates",
        files=[("files", ("doc1.pdf", text_pdf(["page one"], pages=2), "application/pdf")),
               ("files", ("doc2.pdf", text_pdf(["page two"]), "application/pdf"))],
        data={"prefix": "RLG", "start_num": "1", "digits": "6"})
    last = r.headers.get("X-Last-Bates-Number", "")
    is_zip = "application/zip" in r.headers.get("content-type", "")
    names = zip_names(r.content) if is_zip else []
    has_sidecar = any("bates_records.json" in n for n in names)
    if is_zip:
        labeled_zip = r.content
    record("bates: stamp + records", r.status_code == 200 and bool(last) and has_sidecar,
           f"HTTP {r.status_code}, X-Last-Bates-Number={last}, sidecar={has_sidecar}")
except Exception as e:
    record("bates: stamp", False, repr(e))

try:
    if labeled_zip is None:
        record("index: build xlsx", False, "skipped - no labeled zip from bates")
    else:
        r = client.post("/index",
            files=[("file", ("labeled.zip", labeled_zip, "application/zip"))],
            data={"party": "Client", "title_text": "TEST - DOCUMENTS"})
        ctype = r.headers.get("content-type", "")
        record("index: build xlsx", r.status_code == 200 and ("spreadsheet" in ctype or "xlsx" in r.headers.get("content-disposition","")),
               f"HTTP {r.status_code}, ctype={ctype.split(';')[0]}")
except Exception as e:
    record("index: build xlsx", False, repr(e))

# ------------------------------------------------ failure-path probes (no-crash)
BAD_PDF = b"%PDF-1.4\nthis is not really a valid pdf " + b"x" * 200
try:
    r = client.post("/bates",
        files=[("files", ("good.pdf", text_pdf(["ok"]), "application/pdf")),
               ("files", ("bad.pdf", BAD_PDF, "application/pdf"))],
        data={"prefix": "RLG", "start_num": "1", "digits": "6"})
    xff = r.headers.get("X-Failed-Files", "")
    record("bates: failure path no-crash (corrupt file)", r.status_code == 200,
           f"HTTP {r.status_code} (must not be 500), X-Failed-Files={xff or '(absent)'}")
except Exception as e:
    record("bates: failure path", False, repr(e))

try:
    r = client.post("/ocr", files=[("files", ("bad.pdf", BAD_PDF, "application/pdf"))])
    xff = r.headers.get("X-Failed-Files", "")
    parsed = json.loads(xff) if xff else {}
    record("ocr: failure path reports (corrupt file)",
           r.status_code == 200 and "bad.pdf" in parsed,
           f"HTTP {r.status_code}, X-Failed-Files={xff or '(absent)'} (must now report)")
except Exception as e:
    record("ocr: failure path", False, repr(e))

# ---------------------------------------------------------------- 11. FULL PIPELINE
def sse_events(text):
    evs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try: evs.append(json.loads(line[5:].strip()))
            except Exception: pass
    return evs

try:
    # scan
    f1 = text_pdf(["Client file.", "SSN: 123-45-6789", "EIN: 12-3456789"])
    f2 = text_pdf(["Second doc.", "Credit Card: 4111 1111 1111 1111", "Date of Birth: 01/15/1980"])
    r = client.post("/pipeline/scan",
        files=[("files", ("c1.pdf", f1, "application/pdf")),
               ("files", ("c2.pdf", f2, "application/pdf"))])
    scan = r.json()
    scan_id = scan.get("scan_id")
    man = scan.get("manifest", {})
    record("pipeline/scan", r.status_code == 200 and bool(scan_id) and man.get("total_files") == 2,
           f"HTTP {r.status_code}, scan_id={'yes' if scan_id else 'no'}, manifest files={man.get('total_files')}, locked={man.get('locked_count')}")

    # run (unlock skipped, ocr on=>skip-as-searchable, bates on, redact SSN/EIN/CC)
    r = client.post("/pipeline/run", data={
        "scan_id": scan_id,
        "skip_unlock": "true", "skip_ocr": "false", "skip_bates": "false",
        "prefix": "RLG", "start_num": "1", "digits": "6",
        "skip_redact": "false", "presets": ["SSN", "EIN", "Credit Card"],
    })
    evs = sse_events(r.text)
    types = [e.get("type") for e in evs]
    review = next((e for e in evs if e.get("type") == "review_ready"), None)
    run_id = review.get("run_id") if review else None
    record("pipeline/run -> review_ready", r.status_code == 200 and run_id is not None,
           f"HTTP {r.status_code}, stages={types}, total_hits={review.get('total_hits') if review else None}, bates_range={review.get('bates_range') if review else None}")

    # re-redact (add Date of Birth)
    r = client.post(f"/pipeline/re-redact/{run_id}", data={"presets": ["Date of Birth"]})
    evs2 = sse_events(r.text)
    review2 = next((e for e in evs2 if e.get("type") == "review_ready"), None)
    record("pipeline/re-redact", r.status_code == 200 and review2 is not None,
           f"HTTP {r.status_code}, new total_hits={review2.get('total_hits') if review2 else None}")

    # finalize (exercises BatesRecord attribute-access fix while building index)
    r = client.post(f"/pipeline/finalize/{run_id}")
    evs3 = sse_events(r.text)
    done = next((e for e in evs3 if e.get("type") == "done"), None)
    dl_id = done.get("run_id") if done else None
    record("pipeline/finalize -> done (BatesRecord index fix)",
           r.status_code == 200 and dl_id is not None,
           f"HTTP {r.status_code}, types={[e.get('type') for e in evs3]}, download_id={'yes' if dl_id else 'no'}")

    # download + inspect final zip
    r = client.get(f"/pipeline/download/{dl_id}")
    names = zip_names(r.content) if r.status_code == 200 else []
    has_report = any("_pipeline_report.json" in n for n in names)
    has_index = any(n.endswith(".xlsx") for n in names)
    has_pdfs = sum(1 for n in names if n.endswith(".pdf"))
    record("pipeline/download (final zip contents)",
           r.status_code == 200 and has_report and has_pdfs >= 2,
           f"HTTP {r.status_code}, report={has_report}, index_xlsx={has_index}, pdfs={has_pdfs}, names={names}")
except Exception as e:
    import traceback; traceback.print_exc()
    record("pipeline: full flow", False, repr(e))

# ---------------------------------------------------------------- summary
print("\n" + "=" * 64)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"E2E SUMMARY: {passed}/{total} passed")
for feat, ok, detail in results:
    if not ok:
        print(f"   FAILED: {feat} :: {detail}")
sys.exit(0 if passed == total else 1)
