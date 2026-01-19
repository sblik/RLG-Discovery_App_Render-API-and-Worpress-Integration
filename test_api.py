import requests
import os

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

def create_dummy_pdf():
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 100, "Hello World")
    c.save()
    buf.seek(0)
    return buf.getvalue()

def test_unlock():
    print("\nTesting POST /unlock ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'files': ('test.pdf', pdf_bytes, 'application/pdf')}
        response = requests.post(f"{BASE_URL}/unlock", files=files, data={'password_mode': 'Try no password (for unencrypted files)'})
        
        if response.status_code == 200:
            print("POST /unlock: 200 OK")
            if response.headers.get('content-type') == 'application/zip':
                print("Content-Type is application/zip")
                print(f"Received {len(response.content)} bytes")
            else:
                print(f"Unexpected Content-Type: {response.headers.get('content-type')}")
        else:
            print(f"POST /unlock failed: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Test failed: {e}")

def test_bates_simulation():
    print("\nTesting POST /bates (Plugin Simulation) ...")
    try:
        pdf_bytes = create_dummy_pdf()
        files = {'files': ('test.pdf', pdf_bytes, 'application/pdf')}
        # Simulate the exact fields from shortcodes.php
        data = {
            'prefix': 'TEST',
            'start_num': 100,
            'digits': 6,
            'zone': 'Bottom Center (Z2)', # Matches shortcodes.php value
            'zone_padding': 18.0,
            'color_hex': '#FF0000'
        }
        response = requests.post(f"{BASE_URL}/bates", files=files, data=data)
        
        if response.status_code == 200:
            print("POST /bates: 200 OK")
            if response.headers.get('content-type') == 'application/zip':
                print("Content-Type is application/zip")
                print(f"Received {len(response.content)} bytes")
            else:
                print(f"Unexpected Content-Type: {response.headers.get('content-type')}")
        else:
            print(f"POST /bates failed: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    print("Testing API endpoints...")
    test_home()
    test_unlock()
    test_bates_simulation()
