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

# Run the unified app that includes both Backend and UI
CMD ["python", "run_app.py"]
