# StatMan on Railway — need OpenCV system libs (libGL) for cv2 / ultralytics.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python || true \
    && pip install --no-cache-dir --force-reinstall "opencv-python-headless>=4.8,<5" "numpy<2"

COPY . .

ENV PORT=8000
CMD ["sh", "-c", "uvicorn statman.api:app --host 0.0.0.0 --port ${PORT}"]
