#!/usr/bin/env python3
"""
Quick standalone sanity test for Vertex AI from your local environment.

Usage:
  source .venv/bin/activate  # optional but recommended
  export PROJECT_ID=warm-actor-253703
  export REGION=us-central1
  python scripts/sanity_vertex.py

Expected: prints a short greeting from the model. If it fails, the exception
message will indicate whether auth/IAM/API/region/quota is the issue.
"""
import os
import sys

from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel


def main():
    project = os.getenv("PROJECT_ID")
    region = os.getenv("REGION", "us-central1")
    if not project:
        print("PROJECT_ID is not set. Please export PROJECT_ID before running.", file=sys.stderr)
        sys.exit(2)

    print(f"[sanity] Initializing Vertex AI: project={project}, region={region}")
    aiplatform.init(project=project, location=region)

    model_id = os.getenv("MODEL_ID", "gemini-1.5-flash")
    print(f"[sanity] Creating GenerativeModel: {model_id}")
    model = GenerativeModel(model_id)

    prompt = "Say hello in one short sentence."
    print("[sanity] Sending test prompt…")
    resp = model.generate_content(prompt)
    text = getattr(resp, "text", None)
    if text:
        print("[sanity] Response:")
        print(text)
        return

    # Fallback parse
    candidates = getattr(resp, "candidates", None) or []
    for c in candidates:
        content = getattr(c, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        texts = [getattr(p, "text", "") for p in parts]
        joined = "".join([t for t in texts if t])
        if joined:
            print("[sanity] Response:")
            print(joined)
            return

    print("[sanity] No text candidates were returned from the model.")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Print the precise exception for troubleshooting
        print(f"[sanity] Error: {e}", file=sys.stderr)
        sys.exit(1)
