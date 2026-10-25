FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Tesseract is used only for bounded OCR fallback on scanned PDF pages.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
RUN useradd --create-home --uid 10001 chronicle     && mkdir -p /app/uploads     && chown -R chronicle:chronicle /app

USER chronicle
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
