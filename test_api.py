import requests
import io
import zipfile

# Base URL (assuming running locally on default port)
# Base URL (Live Render Deployment)
BASE_URL = "https://rlg-discovery-app-render-api-and-w0b0.onrender.com"


def test_home():
    import time
    max_retries = 5
    for i in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/")
            print(f"GET /: {response.status_code}")
            print(response.json())
            return
        except requests.exceptions.ConnectionError:
            if i < max_retries - 1:
                print(f"Connection failed, retrying in 2s... ({i+1}/{max_retries})")
                time.sleep(2)
            else:
                print(f"Failed to connect to {BASE_URL} after {max_retries} attempts.")
                print("Make sure the server is running: uvicorn main:app --reload")


def create_dummy_pdf(text="Hello World"):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 100, text)
    c.save()
    buf.seek(0)
    return buf.getvalue()


def create_dummy_zip(file_count=2):
    """Create a ZIP containing multiple dummy PDFs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(file_count):
            pdf_bytes = create_dummy_pdf(f"Document {i+1}")
            zf.writestr(f"doc_{i+1}.pdf", pdf_bytes)
    buf.seek(0)
    return buf.getvalue()


def check_content_type(response, expected_type, endpoint_name):
    """Helper to check and print content-type result."""
    actual = response.headers.get('content-type', '')
    if expected_type in actual:
        print(f"  Content-Type: {actual} (expected)")
        print(f"  Received {len(response.content)} bytes")
        return True
    else:
        print(f"  Unexpected Content-Type: {actual} (expected {expected_type})")
        return False


# ---------------------------------------------------------------------------
# UNLOCK
# ---------------------------------------------------------------------------
def test_unlock_single_pdf():
    print("\nTesting POST /unlock (single PDF -> PDF) ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'files': ('test.pdf', pdf_bytes, 'application/pdf')}
        response = requests.post(f"{BASE_URL}/unlock", files=files, data={'password_mode': 'Try no password (for unencrypted files)'})

        if response.status_code == 200:
            print("  POST /unlock: 200 OK")
            check_content_type(response, 'application/pdf', '/unlock single')
        else:
            print(f"  POST /unlock failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


def test_unlock_multi_pdf():
    print("\nTesting POST /unlock (ZIP of 2 PDFs -> ZIP) ...")
    try:
        zip_bytes = create_dummy_zip(2)
        files = {'files': ('docs.zip', zip_bytes, 'application/zip')}
        response = requests.post(f"{BASE_URL}/unlock", files=files, data={'password_mode': 'Try no password (for unencrypted files)'})

        if response.status_code == 200:
            print("  POST /unlock: 200 OK")
            check_content_type(response, 'application/zip', '/unlock multi')
        else:
            print(f"  POST /unlock failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


# ---------------------------------------------------------------------------
# BATES
# ---------------------------------------------------------------------------
def test_bates_single_pdf():
    print("\nTesting POST /bates (single PDF -> PDF) ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'files': ('test.pdf', pdf_bytes, 'application/pdf')}
        data = {
            'prefix': 'TEST',
            'start_num': 100,
            'digits': 6,
            'zone': 'Bottom Center (Z2)',
            'zone_padding': 18.0,
            'color_hex': '#FF0000'
        }
        response = requests.post(f"{BASE_URL}/bates", files=files, data=data)

        if response.status_code == 200:
            print("  POST /bates: 200 OK")
            check_content_type(response, 'application/pdf', '/bates single')
        else:
            print(f"  POST /bates failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


def test_bates_multi_pdf():
    print("\nTesting POST /bates (ZIP of 2 PDFs -> ZIP) ...")
    try:
        zip_bytes = create_dummy_zip(2)
        files = {'files': ('docs.zip', zip_bytes, 'application/zip')}
        data = {
            'prefix': 'TEST',
            'start_num': 1,
            'digits': 6,
            'zone': 'Bottom Center (Z2)',
            'zone_padding': 18.0,
            'color_hex': '#0000FF'
        }
        response = requests.post(f"{BASE_URL}/bates", files=files, data=data)

        if response.status_code == 200:
            print("  POST /bates: 200 OK")
            check_content_type(response, 'application/zip', '/bates multi')
        else:
            print(f"  POST /bates failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


# ---------------------------------------------------------------------------
# REDACT
# ---------------------------------------------------------------------------
def test_redact_single_pdf():
    print("\nTesting POST /redact (single PDF -> PDF) ...")
    try:
        pdf_bytes = create_dummy_pdf("SSN: 123-45-6789")
        files = {'file': ('test.pdf', pdf_bytes, 'application/pdf')}
        data = {
            'presets': 'SSN',
            'case_sensitive': 'false',
            'keep_last_digits': 0,
            'require_ssn_context': 'false'
        }
        response = requests.post(f"{BASE_URL}/redact", files=files, data=data)

        if response.status_code == 200:
            print("  POST /redact: 200 OK")
            check_content_type(response, 'application/pdf', '/redact single')
            hits = response.headers.get('X-Total-Hits', 'N/A')
            print(f"  X-Total-Hits: {hits}")
        else:
            print(f"  POST /redact failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


def test_redact_multi_pdf():
    print("\nTesting POST /redact (ZIP of 2 PDFs -> ZIP) ...")
    try:
        zip_bytes = create_dummy_zip(2)
        files = {'file': ('docs.zip', zip_bytes, 'application/zip')}
        data = {
            'presets': 'SSN',
            'case_sensitive': 'false',
            'keep_last_digits': 0,
            'require_ssn_context': 'false'
        }
        response = requests.post(f"{BASE_URL}/redact", files=files, data=data)

        if response.status_code == 200:
            print("  POST /redact: 200 OK")
            check_content_type(response, 'application/zip', '/redact multi')
        else:
            print(f"  POST /redact failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
def test_ocr_single_pdf():
    print("\nTesting POST /ocr (single PDF -> PDF) ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'files': ('test.pdf', pdf_bytes, 'application/pdf')}
        response = requests.post(f"{BASE_URL}/ocr", files=files)

        if response.status_code == 200:
            print("  POST /ocr: 200 OK")
            check_content_type(response, 'application/pdf', '/ocr single')
        else:
            print(f"  POST /ocr failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


def test_ocr_multi_pdf():
    print("\nTesting POST /ocr (ZIP of 2 PDFs -> ZIP) ...")
    try:
        zip_bytes = create_dummy_zip(2)
        files = {'files': ('docs.zip', zip_bytes, 'application/zip')}
        response = requests.post(f"{BASE_URL}/ocr", files=files)

        if response.status_code == 200:
            print("  POST /ocr: 200 OK")
            check_content_type(response, 'application/zip', '/ocr multi')
        else:
            print(f"  POST /ocr failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


# ---------------------------------------------------------------------------
# INDEX (accepts PDF or ZIP after bates chaining change)
# ---------------------------------------------------------------------------
def test_index_from_zip():
    print("\nTesting POST /index (ZIP input -> XLSX) ...")
    try:
        zip_bytes = create_dummy_zip(2)
        files = {'file': ('bates_labeled.zip', zip_bytes, 'application/zip')}
        data = {'party': 'Client', 'title_text': 'TEST DOCUMENTS'}
        response = requests.post(f"{BASE_URL}/index", files=files, data=data)

        if response.status_code == 200:
            print("  POST /index: 200 OK")
            check_content_type(response, 'application/vnd.openxmlformats', '/index zip')
        else:
            print(f"  POST /index failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


def test_index_from_single_pdf():
    print("\nTesting POST /index (single PDF input -> XLSX) ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'file': ('labeled_doc.pdf', pdf_bytes, 'application/pdf')}
        data = {'party': 'Client', 'title_text': 'TEST DOCUMENTS'}
        response = requests.post(f"{BASE_URL}/index", files=files, data=data)

        if response.status_code == 200:
            print("  POST /index: 200 OK")
            check_content_type(response, 'application/vnd.openxmlformats', '/index pdf')
        else:
            print(f"  POST /index failed: {response.status_code}")
            print(f"  {response.text}")
    except Exception as e:
        print(f"  Test failed: {e}")


if __name__ == "__main__":
    print("Testing API endpoints...\n")
    test_home()

    # Single PDF -> PDF
    test_unlock_single_pdf()
    test_bates_single_pdf()
    test_redact_single_pdf()
    test_ocr_single_pdf()

    # Multi PDF -> ZIP
    test_unlock_multi_pdf()
    test_bates_multi_pdf()
    test_redact_multi_pdf()
    test_ocr_multi_pdf()

    # Index (accepts both PDF and ZIP)
    test_index_from_zip()
    test_index_from_single_pdf()

    print("\n--- All tests complete ---")
