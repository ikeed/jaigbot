# Minimal container for FastAPI and Chainlit apps running on Cloud Run
FROM python:3.13-slim-bookworm

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

# .git isn't copied into the image (see .dockerignore), so the deploy workflow
# passes the commit SHA in at build time instead of it being read from git at
# runtime -- see app/services/storage_service.py.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

# Run the unified app that includes both Backend and UI
CMD ["python", "run_app.py"]
