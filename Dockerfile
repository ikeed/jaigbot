# Minimal container for FastAPI and Chainlit apps running on Cloud Run
FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code into the container
COPY . .

# Back-end URL Chainlit uses to reach the FastAPI service
ENV BACKEND_URL=http://localhost:8000/chat
# Force Chainlit UI language to English by default (can be overridden at deploy time)
ENV CHAINLIT_LOCALE=en

# Chainlit stays in the foreground so the container remains healthy.
# Run Uvicorn on port 8000 and Chainlit on the Cloud Run port.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 & chainlit run chainlit_app.py --host 0.0.0.0 --port ${PORT}"]
