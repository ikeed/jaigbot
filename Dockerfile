# Minimal container for FastAPI app running on Cloud Run
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code
COPY app ./app

# Cloud Run provides PORT
ENV PORT=8080

# Use shell form so ${PORT} env is expanded
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
