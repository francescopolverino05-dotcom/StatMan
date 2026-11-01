# StatMan (stats viewer + exporter) on Railway. Pure-Python stack: no system libs needed.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
CMD ["sh", "-c", "uvicorn statman.api:app --host 0.0.0.0 --port ${PORT}"]
