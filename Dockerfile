FROM python:3.11-slim

# Install minimal system dependencies (OpenGL for image processing)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download OnnxTR models so first request isn't slow
RUN python -c "from onnxtr.models import ocr_predictor; ocr_predictor(det_arch='fast_tiny', reco_arch='crnn_mobilenet_v3_small')"

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
