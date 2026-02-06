"""
Comprehensive input test for all Discovery One-Stop API endpoints.
Tests every accepted input combination per tool.
"""
import requests
import io
import zipfile
import sys

BASE_URL = "https://rlg-discovery-app-render-api-and-w0b0.onrender.com"

passed = 0
failed = 0
errors = []


def create_pdf(text="Hello World"):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.drawString(100, 600, "Contact: john@example.com")
    c.drawString(100, 500, "Phone: 555-123-4567")
    c.drawString(100, 400, "SSN: 123-45-6789")
    c.drawString(100, 300, "Date: 01/15/2024")
    c.drawString(100, 200, "Account: 12345678")
    c.save()
    buf.seek(0)
    return buf.getvalue()


def create_zip(file_count=2):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(file_count):
            pdf_bytes = create_pdf(f"Document {i+1}")
            zf.writestr(f"doc_{i+1}.pdf", pdf_bytes)
    buf.seek(0)
    return buf.getvalue()


def create_zip_with_folders():
    """ZIP with subfolder structure for organize/index testing."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Medical Records/report_2023.pdf", create_pdf("Medical 2023"))
        zf.writestr("Tax Documents/w2_2022.pdf", create_pdf("Tax 2022"))
        zf.writestr("Correspondence/letter_2021.pdf", create_pdf("Letter 2021"))
    buf.seek(0)
    return buf.getvalue()


def create_image():
    """Create a simple PNG image."""
    from PIL import Image
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def check(test_name, response, expected_type, extra_checks=None):
    global passed, failed, errors
    actual_type = response.headers.get("content-type", "")
    disposition = response.headers.get("content-disposition", "")
    status = response.status_code

    ok = True
    details = []

    if status != 200:
        ok = False
        try:
            detail = response.json().get("detail", response.text[:200])
        except Exception:
            detail = response.text[:200]
        details.append(f"HTTP {status}: {detail}")

    elif expected_type not in actual_type:
        ok = False
        details.append(f"Content-Type: got '{actual_type}', expected '{expected_type}'")

    else:
        # Validate response bytes
        content = response.content
        if expected_type == "application/pdf":
            if not content[:4] == b"%PDF":
                ok = False
                details.append(f"Response not valid PDF (starts with {content[:8]})")
        elif expected_type == "application/zip":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    entries = zf.namelist()
                    if not entries:
                        ok = False
                        details.append("ZIP is empty")
                    else:
                        details.append(f"ZIP entries: {entries}")
            except zipfile.BadZipFile:
                ok = False
                details.append("Invalid ZIP file")
        elif expected_type == "application/vnd.openxmlformats":
            if len(content) < 100:
                ok = False
                details.append(f"XLSX too small ({len(content)} bytes)")

    if extra_checks and ok:
        for label, header_name, expected_present in extra_checks:
            val = response.headers.get(header_name, "")
            if expected_present and not val:
                details.append(f"Missing header: {header_name}")
            elif val:
                details.append(f"{header_name}: {val}")

    if ok:
        passed += 1
        icon = "\033[92mPASS\033[0m"
    else:
        failed += 1
        icon = "\033[91mFAIL\033[0m"
        errors.append((test_name, details))

    size = len(response.content)
    print(f"  [{icon}] {test_name} ({size:,} bytes)")
    for d in details:
        print(f"         {d}")


# =============================================================================
print("=" * 70)
print("COMPREHENSIVE API INPUT TESTS")
print(f"Target: {BASE_URL}")
print("=" * 70)

# Wake up the server
print("\nWaking up server...")
try:
    r = requests.get(f"{BASE_URL}/", timeout=30)
    print(f"  Server ready: {r.status_code}\n")
except Exception as e:
    print(f"  Server unreachable: {e}")
    sys.exit(1)

# =============================================================================
# 1. UNLOCK
# =============================================================================
print("-" * 70)
print("1. UNLOCK (/unlock)")
print("-" * 70)

# 1a. Single PDF, try no password
r = requests.post(f"{BASE_URL}/unlock",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"password_mode": "Try no password (for unencrypted files)"})
check("Single PDF + no password → PDF", r, "application/pdf")

# 1b. Single PDF, single password mode (empty password for unencrypted)
r = requests.post(f"{BASE_URL}/unlock",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"password_mode": "Single password for all", "password_for_all": ""})
check("Single PDF + single password mode → PDF", r, "application/pdf")

# 1c. ZIP of 2 PDFs → ZIP
r = requests.post(f"{BASE_URL}/unlock",
    files={"files": ("docs.zip", create_zip(2), "application/zip")},
    data={"password_mode": "Try no password (for unencrypted files)"})
check("ZIP of 2 PDFs + no password → ZIP", r, "application/zip")

# 1d. Multiple individual PDFs → ZIP
r = requests.post(f"{BASE_URL}/unlock",
    files=[
        ("files", ("a.pdf", create_pdf("Doc A"), "application/pdf")),
        ("files", ("b.pdf", create_pdf("Doc B"), "application/pdf")),
    ],
    data={"password_mode": "Try no password (for unencrypted files)"})
check("2 individual PDFs → ZIP", r, "application/zip")

# =============================================================================
# 2. ORGANIZE
# =============================================================================
print(f"\n{'-' * 70}")
print("2. ORGANIZE (/organize)")
print("-" * 70)

# 2a. ZIP with year-named files, default settings
r = requests.post(f"{BASE_URL}/organize",
    files={"files": ("docs.zip", create_zip_with_folders(), "application/zip")},
    data={"min_year": 1900, "max_year": 2099, "unknown_folder": "Unknown"})
check("ZIP with year files + defaults → ZIP", r, "application/zip")

# 2b. Single PDF
r = requests.post(f"{BASE_URL}/organize",
    files={"files": ("report_2023.pdf", create_pdf("2023 report"), "application/pdf")},
    data={"min_year": 2000, "max_year": 2025, "unknown_folder": "Unsorted"})
check("Single PDF + custom year range → ZIP", r, "application/zip")

# 2c. Multiple individual PDFs
r = requests.post(f"{BASE_URL}/organize",
    files=[
        ("files", ("invoice_2022.pdf", create_pdf("2022"), "application/pdf")),
        ("files", ("letter_2023.pdf", create_pdf("2023"), "application/pdf")),
    ],
    data={"min_year": 1900, "max_year": 2099, "unknown_folder": "Unknown"})
check("Multiple PDFs with years → ZIP", r, "application/zip")

# =============================================================================
# 3. BATES LABELER
# =============================================================================
print(f"\n{'-' * 70}")
print("3. BATES LABELER (/bates)")
print("-" * 70)

# 3a. Single PDF, Bottom Right zone
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"prefix": "EX", "start_num": 1, "digits": 6,
          "zone": "Bottom Right (Z3)", "zone_padding": 18,
          "color_hex": "#0000FF", "font_size": 12})
check("Single PDF + Bottom Right → PDF", r, "application/pdf",
      [("last bates", "X-Last-Bates-Number", True)])

# 3b. Single PDF, Bottom Center zone
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"prefix": "DOC", "start_num": 100, "digits": 8,
          "zone": "Bottom Center (Z2)", "zone_padding": 24,
          "color_hex": "#FF0000", "font_size": 14})
check("Single PDF + Bottom Center + red → PDF", r, "application/pdf",
      [("last bates", "X-Last-Bates-Number", True)])

# 3c. Single PDF, Bottom Left zone
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"prefix": "", "start_num": 1, "digits": 6,
          "zone": "Bottom Left (Z1)", "zone_padding": 18,
          "color_hex": "#000000", "font_size": 10})
check("Single PDF + Bottom Left + no prefix → PDF", r, "application/pdf",
      [("last bates", "X-Last-Bates-Number", True)])

# 3d. ZIP of PDFs
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("docs.zip", create_zip(3), "application/zip")},
    data={"prefix": "BATCH", "start_num": 1, "digits": 6,
          "zone": "Bottom Right (Z3)", "zone_padding": 18,
          "color_hex": "#0000FF"})
check("ZIP of 3 PDFs → ZIP", r, "application/zip",
      [("last bates", "X-Last-Bates-Number", True)])

# 3e. Bold font
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"prefix": "BOLD", "start_num": 1, "digits": 6,
          "zone": "Bottom Right (Z3)", "zone_padding": 18,
          "color_hex": "#0000FF", "font_bold": "true", "font_size": 16})
check("Single PDF + bold font → PDF", r, "application/pdf")

# 3f. Punch margin + border
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    data={"prefix": "PM", "start_num": 1, "digits": 6,
          "zone": "Bottom Right (Z3)", "zone_padding": 18,
          "color_hex": "#0000FF", "left_punch_margin": 36,
          "border_all_pt": 12})
check("Single PDF + punch margin + border → PDF", r, "application/pdf")

# 3g. Image file (PNG)
r = requests.post(f"{BASE_URL}/bates",
    files={"files": ("photo.png", create_image(), "image/png")},
    data={"prefix": "IMG", "start_num": 1, "digits": 6,
          "zone": "Bottom Center (Z2)", "zone_padding": 18,
          "color_hex": "#0000FF"})
check("Single PNG image → PNG", r, "image/png")

# =============================================================================
# 4. REDACT
# =============================================================================
print(f"\n{'-' * 70}")
print("4. REDACT (/redact)")
print("-" * 70)

# 4a. Single PDF, SSN preset (no context required)
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "SSN", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "false"})
check("Single PDF + SSN preset → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4b. Single PDF, SSN with context required
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "SSN", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "true"})
check("Single PDF + SSN w/ context required → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4c. Single PDF, Email preset
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "Email", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "true"})
check("Single PDF + Email preset → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4d. Single PDF, Phone preset
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "Phone", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "true"})
check("Single PDF + Phone preset → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4e. Single PDF, Date preset
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "Date", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "true"})
check("Single PDF + Date preset → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4f. Single PDF, 8-digit number preset
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "8-digit number", "case_sensitive": "false",
          "keep_last_digits": 0, "require_ssn_context": "true"})
check("Single PDF + 8-digit preset → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4g. Multiple presets at once
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data=[("presets", "SSN"), ("presets", "Email"), ("presets", "Phone"),
          ("case_sensitive", "false"), ("keep_last_digits", "0"),
          ("require_ssn_context", "false")])
check("Single PDF + SSN+Email+Phone presets → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4h. Literal patterns only (no presets)
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"literal_patterns": "Hello World,john@example.com",
          "case_sensitive": "false", "keep_last_digits": "0",
          "require_ssn_context": "true"})
check("Single PDF + literal patterns → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4i. Regex patterns only
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"regex_patterns": r"\b\d{3}-\d{3}-\d{4}\b",
          "case_sensitive": "false", "keep_last_digits": "0",
          "require_ssn_context": "true"})
check("Single PDF + custom regex → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4j. SSN with keep_last_digits=4
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"presets": "SSN", "case_sensitive": "false",
          "keep_last_digits": "4", "require_ssn_context": "false"})
check("Single PDF + SSN keep last 4 → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4k. Case sensitive
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"literal_patterns": "Hello World",
          "case_sensitive": "true", "keep_last_digits": "0",
          "require_ssn_context": "true"})
check("Single PDF + literal case-sensitive → PDF", r, "application/pdf",
      [("hits", "X-Total-Hits", True)])

# 4l. ZIP of PDFs
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("docs.zip", create_zip(2), "application/zip")},
    data={"presets": "SSN", "case_sensitive": "false",
          "keep_last_digits": "0", "require_ssn_context": "false"})
check("ZIP of 2 PDFs + SSN → ZIP", r, "application/zip",
      [("hits", "X-Total-Hits", True)])

# 4m. No patterns (should fail with 400)
r = requests.post(f"{BASE_URL}/redact",
    files={"file": ("test.pdf", create_pdf(), "application/pdf")},
    data={"case_sensitive": "false", "keep_last_digits": "0",
          "require_ssn_context": "true"})
if r.status_code == 400:
    passed += 1
    print(f"  [\033[92mPASS\033[0m] No patterns → 400 error (expected)")
else:
    failed += 1
    errors.append(("No patterns → 400", [f"Got {r.status_code} instead of 400"]))
    print(f"  [\033[91mFAIL\033[0m] No patterns → expected 400, got {r.status_code}")

# =============================================================================
# 5. INDEX
# =============================================================================
print(f"\n{'-' * 70}")
print("5. DISCOVERY INDEX (/index)")
print("-" * 70)

# 5a. ZIP input, Client party
r = requests.post(f"{BASE_URL}/index",
    files={"file": ("labeled.zip", create_zip(2), "application/zip")},
    data={"party": "Client", "title_text": "TEST - CLIENT DOCUMENTS"})
check("ZIP + Client party → XLSX", r, "application/vnd.openxmlformats")

# 5b. ZIP input, OP party
r = requests.post(f"{BASE_URL}/index",
    files={"file": ("labeled.zip", create_zip(2), "application/zip")},
    data={"party": "OP", "title_text": "OPPOSING PARTY DOCUMENTS"})
check("ZIP + OP party → XLSX", r, "application/vnd.openxmlformats")

# 5c. Single PDF input
r = requests.post(f"{BASE_URL}/index",
    files={"file": ("doc.pdf", create_pdf(), "application/pdf")},
    data={"party": "Client", "title_text": "SINGLE DOC INDEX"})
check("Single PDF → XLSX", r, "application/vnd.openxmlformats")

# 5d. ZIP with folder structure
r = requests.post(f"{BASE_URL}/index",
    files={"file": ("structured.zip", create_zip_with_folders(), "application/zip")},
    data={"party": "Client", "title_text": "STRUCTURED INDEX"})
check("ZIP with subfolders → XLSX", r, "application/vnd.openxmlformats")

# =============================================================================
# 6. OCR
# =============================================================================
print(f"\n{'-' * 70}")
print("6. OCR (/ocr)")
print("-" * 70)

# 6a. Single PDF
r = requests.post(f"{BASE_URL}/ocr",
    files={"files": ("test.pdf", create_pdf(), "application/pdf")},
    timeout=120)
check("Single PDF → PDF", r, "application/pdf")

# 6b. ZIP of PDFs
r = requests.post(f"{BASE_URL}/ocr",
    files={"files": ("docs.zip", create_zip(2), "application/zip")},
    timeout=120)
check("ZIP of 2 PDFs → ZIP", r, "application/zip")

# 6c. Multiple individual PDFs
r = requests.post(f"{BASE_URL}/ocr",
    files=[
        ("files", ("a.pdf", create_pdf("Doc A"), "application/pdf")),
        ("files", ("b.pdf", create_pdf("Doc B"), "application/pdf")),
    ],
    timeout=120)
check("2 individual PDFs → ZIP", r, "application/zip")

# =============================================================================
# SUMMARY
# =============================================================================
print(f"\n{'=' * 70}")
print(f"RESULTS: \033[92m{passed} passed\033[0m, \033[91m{failed} failed\033[0m out of {passed + failed} tests")
print("=" * 70)

if errors:
    print("\nFAILED TESTS:")
    for name, details in errors:
        print(f"  - {name}")
        for d in details:
            print(f"    {d}")

sys.exit(1 if failed else 0)