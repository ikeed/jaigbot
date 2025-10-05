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

# Backend URL for Chainlit to reach the FastAPI service running in the same container
ENV BACKEND_URL=http://localhost:8000/chat

# Start the FastAPI backend on port 8000 in the background and run the Chainlit UI on the port provided by Cloud Run (PORT)
# Cloud Run sets the PORT environment variable automatically. Chainlit will bind to this port.
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port 8000 & chainlit run chainlit_app.py --host 0.0.0.0 --port ${PORT} --no-browser"
