"""Edge-case hardening suite for the merged v1.9.0 app (pre-production).

Covers input validation, redaction false-positive controls, pipeline error
paths, locked-file unlock in the pipeline, auth enforcement, and format edges.
Run:  PYTHONPATH=<worktree> ./.venv/bin/python /tmp/rlg_edge.py
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
results = []

def record(feature, ok, detail=""):
    results.append((feature, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {feature} :: {detail}")

# ---- fixtures ----
def text_pdf(lines, pages=1) -> bytes:
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=letter)
    for _ in range(pages):
        y = 720
        for ln in lines:
            c.drawString(72, y, ln); y -= 24
        c.showPage()
    c.save(); return buf.getvalue()

def locked_pdf(password) -> bytes:
    pdf = pikepdf.open(io.BytesIO(text_pdf(["secret content"])))
    out = io.BytesIO(); pdf.save(out, encryption=pikepdf.Encryption(user=password, owner=password))
    return out.getvalue()

def png_bytes(text="SCAN 12345") -> bytes:
    img = Image.new("RGB", (600, 200), "white"); ImageDraw.Draw(img).text((20, 80), text, fill="black")
    b = io.BytesIO(); img.save(b, format="PNG"); return b.getvalue()

def tiff_bytes(pages=2) -> bytes:
    imgs = []
    for i in range(pages):
        im = Image.new("RGB", (500, 300), "white"); ImageDraw.Draw(im).text((20, 120), f"TIFF page {i+1}", fill="black"); imgs.append(im)
    b = io.BytesIO(); imgs[0].save(b, format="TIFF", save_all=True, append_images=imgs[1:]); return b.getvalue()

def make_zip(entries) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return b.getvalue()

def hits(r):
    return int(r.headers.get("X-Total-Hits", "-1"))

def zip_names(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z: return z.namelist()

def not_500(r): return r.status_code != 500

# ============================================================ A. INPUT VALIDATION
try:
    r = client.post("/redact", files=[], data={"presets": ["SSN"]})
    record("A1 redact: no files -> 4xx not 500", r.status_code in (400, 422), f"HTTP {r.status_code}")
except Exception as e:
    record("A1 redact: no files", False, repr(e))

BADZIP = b"PK\x03\x04 not a zip"
try:  # /bates aborts the whole batch on a corrupt top-level ZIP -> 400
    r = client.post("/bates", files=[("files", ("bad.zip", BADZIP, "application/zip"))], data={"prefix": "X"})
    record("A2a bates: corrupt ZIP -> 400 (abort)", r.status_code == 400, f"HTTP {r.status_code}")
except Exception as e:
    record("A2a bates: corrupt ZIP", False, repr(e))
try:  # /unlock treats it as a per-file failure -> 200 + reported in X-Failed-Files (graceful)
    r = client.post("/unlock", files=[("files", ("bad.zip", BADZIP, "application/zip"))],
                    data={"password_mode": "Try no password"})
    xff = r.headers.get("X-Failed-Files", "")
    record("A2b unlock: corrupt ZIP -> 200 + reported (graceful)", r.status_code == 200 and "bad.zip" in xff,
           f"HTTP {r.status_code}, X-Failed-Files={xff or '(absent)'}")
except Exception as e:
    record("A2b unlock: corrupt ZIP", False, repr(e))

try:
    r = client.post("/redact", files=[("files", ("notes.txt", b"hello world", "text/plain"))], data={"presets": ["SSN"]})
    record("A3 redact: non-PDF -> 400", r.status_code == 400, f"HTTP {r.status_code}")
except Exception as e:
    record("A3 redact: non-PDF", False, repr(e))

try:
    r = client.post("/bates", files=[("files", ("empty.zip", make_zip([]), "application/zip"))], data={"prefix": "X"})
    record("A4 bates: empty ZIP -> 400", r.status_code == 400, f"HTTP {r.status_code}")
except Exception as e:
    record("A4 bates: empty ZIP", False, repr(e))

try:
    junk = make_zip([("__MACOSX/._x", b"junk"), (".DS_Store", b"junk")])
    r = client.post("/bates", files=[("files", ("junk.zip", junk, "application/zip"))], data={"prefix": "X"})
    record("A5 bates: ZIP of only junk -> 400", r.status_code == 400, f"HTTP {r.status_code}")
except Exception as e:
    record("A5 bates: junk ZIP", False, repr(e))

try:
    r = client.post("/redact", files=[("files", ("zero.pdf", b"", "application/pdf"))], data={"presets": ["SSN"]})
    record("A6 redact: zero-byte PDF -> not 500", not_500(r), f"HTTP {r.status_code}")
except Exception as e:
    record("A6 redact: zero-byte", False, repr(e))

# ============================================================ B. ZIP BATCH UNWRAP
try:
    z = make_zip([("d1.pdf", text_pdf(["one"])), ("d2.pdf", text_pdf(["two"]))])
    r = client.post("/bates", files=[("files", ("batch.zip", z, "application/zip"))], data={"prefix": "RLG", "start_num": "1", "digits": "6"})
    names = zip_names(r.content) if "zip" in r.headers.get("content-type", "") else []
    pdfs = [n for n in names if n.endswith(".pdf")]
    record("B1 bates: ZIP batch unwrap (2 pdfs)", r.status_code == 200 and len(pdfs) == 2, f"HTTP {r.status_code}, pdfs={pdfs}")
except Exception as e:
    record("B1 bates: ZIP batch", False, repr(e))

# ============================================================ C. REDACTION CORRECTNESS
def redact(lines, presets, **extra):
    data = {"presets": presets}; data.update(extra)
    return client.post("/redact", files=[("files", ("d.pdf", text_pdf(lines), "application/pdf"))], data=data)

try:
    r = redact(["My number is 123-45-6789 (no label)"], ["SSN"], require_ssn_context="true")
    record("C1 SSN no-context + require=ON -> 0 hits (no false positive)", r.status_code == 200 and hits(r) == 0, f"hits={hits(r)}")
except Exception as e:
    record("C1 SSN no-context guard", False, repr(e))

try:
    r = redact(["My number is 123-45-6789 (no label)"], ["SSN"], require_ssn_context="false")
    record("C2 SSN no-context + require=OFF -> >=1 hit", r.status_code == 200 and hits(r) >= 1, f"hits={hits(r)}")
except Exception as e:
    record("C2 SSN require off", False, repr(e))

try:
    r = redact(["Reference 12-3456789 in the contract"], ["EIN"])
    record("C3 EIN no-context -> 0 hits (guard)", r.status_code == 200 and hits(r) == 0, f"hits={hits(r)} (informational if !=0)")
except Exception as e:
    record("C3 EIN no-context", False, repr(e))

try:
    r = redact(["EIN: 12-3456789"], ["EIN"])
    record("C4 EIN with context -> >=1 hit", r.status_code == 200 and hits(r) >= 1, f"hits={hits(r)}")
except Exception as e:
    record("C4 EIN with context", False, repr(e))

try:
    r = redact(["Document filed on 01/15/1980 at court"], ["Date of Birth"])
    record("C5 DOB plain date (no label) -> 0 hits", r.status_code == 200 and hits(r) == 0, f"hits={hits(r)}")
except Exception as e:
    record("C5 DOB labeled-only", False, repr(e))

try:
    r = redact(["Date of Birth: 01/15/1980"], ["Date of Birth"])
    record("C6 DOB labeled -> >=1 hit", r.status_code == 200 and hits(r) >= 1, f"hits={hits(r)}")
except Exception as e:
    record("C6 DOB labeled hit", False, repr(e))

try:
    r = redact(["Card 4111 1111 1111 1111", "Order 1234 5678 9012 3456 (not a card)"], ["Credit Card"])
    record("C7 Credit Card: valid Visa hits, non-card ignored", r.status_code == 200 and hits(r) == 1, f"hits={hits(r)} (expect 1)")
except Exception as e:
    record("C7 credit card", False, repr(e))

try:
    # Swagger sends multiple presets comma-joined as ONE string
    r = client.post("/redact", files=[("files", ("d.pdf", text_pdf(["SSN: 123-45-6789", "EIN: 12-3456789"]), "application/pdf"))],
                    data={"presets": ["SSN,EIN"]})
    record("C8 Swagger comma-joined presets split -> >=2 hits", r.status_code == 200 and hits(r) >= 2, f"hits={hits(r)}")
except Exception as e:
    record("C8 comma-joined presets", False, repr(e))

try:
    r = redact(["SSN: 123-45-6789"], ["SSN"], keep_last_digits="4")
    record("C9 keep_last_digits=4 -> still hits", r.status_code == 200 and hits(r) >= 1, f"hits={hits(r)}")
except Exception as e:
    record("C9 keep_last_digits", False, repr(e))

try:
    r = client.post("/redact", files=[("files", ("d.pdf", text_pdf(["Matter SECRET-CODE-42 here"]), "application/pdf"))],
                    data={"presets": [], "regex_patterns": r"SECRET-CODE-\d+"})
    record("C10 custom regex pattern -> >=1 hit", r.status_code == 200 and hits(r) >= 1, f"hits={hits(r)}")
except Exception as e:
    record("C10 custom regex", False, repr(e))

try:
    r = client.post("/redact", files=[("files", ("d.pdf", text_pdf(["nothing sensitive here"]), "application/pdf"))],
                    data={"presets": []})
    record("C11 no patterns -> 400 (requires >=1 pattern)", r.status_code == 400, f"HTTP {r.status_code}")
except Exception as e:
    record("C11 no patterns", False, repr(e))

try:
    r = client.post("/redact", files=[("files", ("d.pdf", text_pdf(["SSN: 123-45-6789"]) , "application/pdf")),
                                        ("files", ("d2.pdf", text_pdf(["page1 nothing"]) + b"", "application/pdf"))],
                    data={"presets": ["SSN"]})
    # multi-page check: build a 2-page pdf with SSN on page 2
    r2 = client.post("/redact", files=[("files", ("mp.pdf", text_pdf(["page", "SSN: 123-45-6789"], pages=2), "application/pdf"))],
                     data={"presets": ["SSN"]})
    record("C12 multi-page redaction -> hits", r2.status_code == 200 and hits(r2) >= 1, f"hits={hits(r2)}")
except Exception as e:
    record("C12 multi-page", False, repr(e))

# ============================================================ D. BATES EDGE
try:
    # stamp once
    r1 = client.post("/bates", files=[("files", ("a.pdf", text_pdf(["x"]), "application/pdf"))],
                     data={"prefix": "RLG", "start_num": "1", "digits": "6"})
    labeled = r1.content if "zip" in r1.headers.get("content-type", "") else None
    if labeled:
        r2 = client.post("/bates", files=[("files", ("labeled.zip", labeled, "application/zip"))],
                         data={"prefix": "RLG", "start_num": "1", "digits": "6"})
        record("D1 pre-labeled detection (re-bates no crash)", r2.status_code == 200, f"HTTP {r2.status_code}, X-Last={r2.headers.get('X-Last-Bates-Number')}")
    else:
        # single file returns bare pdf; still fine
        record("D1 pre-labeled detection", r1.status_code == 200, f"single-file output HTTP {r1.status_code}")
except Exception as e:
    record("D1 pre-labeled", False, repr(e))

try:
    r = client.post("/bates", files=[("files", ("img.png", png_bytes(), "image/png"))],
                    data={"prefix": "IMG", "start_num": "1", "digits": "6", "zone": "Bottom Right (Z3)", "color_hex": "#FF0000"})
    record("D2 bates on image + custom zone/color", r.status_code == 200, f"HTTP {r.status_code}")
except Exception as e:
    record("D2 bates image", False, repr(e))

# ============================================================ E. OCR EDGE
try:
    r = client.post("/ocr", files=[("files", ("multi.tiff", tiff_bytes(2), "image/tiff"))])
    record("E1 OCR multi-page TIFF -> not 500", not_500(r), f"HTTP {r.status_code}, ctype={r.headers.get('content-type','').split(';')[0]}")
except Exception as e:
    record("E1 OCR TIFF", False, repr(e))

try:
    searchable = text_pdf(["This document already contains a complete searchable text layer",
                           "added by Preview, so OCR should detect it and skip processing."])
    r = client.post("/ocr", files=[("files", ("searchable.pdf", searchable, "application/pdf")),
                                     ("files", ("scan.png", png_bytes(), "image/png"))])
    record("E2 OCR mixed batch (searchable skipped, image OCR'd)",
           r.status_code == 200 and r.headers.get("X-Already-Searchable") == "1",
           f"HTTP {r.status_code}, X-Already-Searchable={r.headers.get('X-Already-Searchable')}")
except Exception as e:
    record("E2 OCR mixed", False, repr(e))

# ============================================================ F. ORGANIZE EDGE
def strip_meta(b):
    p = pikepdf.open(io.BytesIO(b))
    try: del p.docinfo
    except Exception: pass
    try: del p.Root.Metadata
    except Exception: pass
    out = io.BytesIO(); p.save(out); return out.getvalue()

try:  # cascade (filename->metadata->content): PDF metadata CreationDate provides the year
    r = client.post("/organize", files=[("files", ("noyear.pdf", text_pdf(["no date in content"]), "application/pdf"))], data={})
    names = zip_names(r.content) if r.status_code == 200 else []
    foldered = any("/" in n for n in names)
    record("F1a organize: undated file filed by metadata-date cascade", r.status_code == 200 and foldered, f"entries={names}")
except Exception as e:
    record("F1a organize cascade", False, repr(e))

try:  # no filename year + no content year + metadata stripped -> Unknown
    nodate = strip_meta(text_pdf(["no date in content here"]))
    r = client.post("/organize", files=[("files", ("file.pdf", nodate, "application/pdf"))], data={"unknown_folder": "Unknown"})
    names = zip_names(r.content) if r.status_code == 200 else []
    record("F1b organize: truly undated -> Unknown folder", r.status_code == 200 and any("nknown" in n for n in names),
           f"entries={names}")
except Exception as e:
    record("F1b organize unknown", False, repr(e))

# ============================================================ G. PIPELINE EDGE
def sse(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try: out.append(json.loads(line[5:].strip()))
            except Exception: pass
    return out

try:
    r = client.post("/pipeline/run", data={"scan_id": "does-not-exist", "skip_unlock": "true"})
    record("G1 pipeline/run bad scan_id -> 404", r.status_code == 404, f"HTTP {r.status_code}")
except Exception as e:
    record("G1 bad scan_id", False, repr(e))

try:
    r = client.post("/pipeline/finalize/nope-not-real")
    record("G2 pipeline/finalize bad run_id -> 404", r.status_code == 404, f"HTTP {r.status_code}")
except Exception as e:
    record("G2 bad finalize id", False, repr(e))

try:
    r = client.post("/pipeline/re-redact/nope", data={"presets": ["SSN"]})
    record("G3 pipeline/re-redact bad run_id -> 404", r.status_code == 404, f"HTTP {r.status_code}")
except Exception as e:
    record("G3 bad re-redact id", False, repr(e))

try:
    r = client.get("/pipeline/download/nope")
    record("G4 pipeline/download bad id -> 4xx", 400 <= r.status_code < 500, f"HTTP {r.status_code}")
except Exception as e:
    record("G4 bad download id", False, repr(e))

try:
    # locked file through the pipeline unlock stage
    r = client.post("/pipeline/scan", files=[("files", ("locked.pdf", locked_pdf("pw123"), "application/pdf"))])
    man = r.json().get("manifest", {}); sid = r.json().get("scan_id")
    scan_ok = r.status_code == 200 and man.get("locked_count") == 1
    record("G5 pipeline/scan detects locked file", scan_ok, f"locked_count={man.get('locked_count')}")
    rr = client.post("/pipeline/run", data={"scan_id": sid, "skip_unlock": "false", "password_mode": "all",
                                            "password_for_all": "pw123", "skip_ocr": "true", "skip_bates": "true", "skip_redact": "true"})
    evs = sse(rr.text); rev = next((e for e in evs if e.get("type") == "review_ready"), None)
    types = [e.get("type") for e in evs]
    record("G6 pipeline unlock stage (locked file + password)", rr.status_code == 200 and rev is not None and "stage_error" not in types,
           f"HTTP {rr.status_code}, stages={types}")
    if rev:
        rf = client.post(f"/pipeline/finalize/{rev['run_id']}")
        d = next((e for e in sse(rf.text) if e.get("type") == "done"), None)
        record("G7 pipeline finalize after unlock-only run", rf.status_code == 200 and d is not None, f"HTTP {rf.status_code}")
except Exception as e:
    import traceback; traceback.print_exc()
    record("G5-G7 pipeline locked-file flow", False, repr(e))

# ============================================================ H. AUTH ENFORCEMENT
try:
    main._API_KEY = "secret-test-key"           # enable enforcement (read as module global)
    r_noauth = client.post("/pipeline/scan", files=[("files", ("a.pdf", text_pdf(["x"]), "application/pdf"))])
    r_auth = client.post("/pipeline/scan", files=[("files", ("a.pdf", text_pdf(["x"]), "application/pdf"))],
                         headers={"X-API-Key": "secret-test-key"})
    record("H1 API key enforced: missing -> 403", r_noauth.status_code == 403, f"HTTP {r_noauth.status_code}")
    record("H2 API key enforced: correct -> 200", r_auth.status_code == 200, f"HTTP {r_auth.status_code}")
finally:
    main._API_KEY = ""                          # restore disabled (don't break other runs)
    r_back = client.get("/")
    record("H3 auth disabled after reset -> 200", r_back.status_code == 200, f"HTTP {r_back.status_code}")

# ============================================================ summary
print("\n" + "=" * 64)
passed = sum(1 for _, ok, _ in results if ok)
print(f"EDGE SUMMARY: {passed}/{len(results)} passed")
for feat, ok, detail in results:
    if not ok:
        print(f"   FAILED: {feat} :: {detail}")
sys.exit(0 if passed == len(results) else 1)
