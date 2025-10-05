#!/usr/bin/env python3
"""
Diagnose Vertex AI model access for Gemini in your current environment.

What it does:
- Prints ADC account and project/region in use
- Lists publisher models from google/publishers for your project+region
- Attempts a short generate with MODEL_ID and any MODEL_FALLBACKS

Usage:
  source .venv/bin/activate
  export PROJECT_ID=warm-actor-253703
  export REGION=us-central1
  # optional overrides
  export MODEL_ID=gemini-2.5-flash
  export MODEL_FALLBACKS="gemini-2.5-flash-001"
  python scripts/check_model_access.py

Exit codes:
  0 = success (at least one model generated successfully)
  1 = ran but no model could generate; see printed errors
  2 = configuration/auth issue (missing env or ADC)
"""
from __future__ import annotations
import os
import sys
import json
from typing import List

import google.auth
from google.auth.transport.requests import AuthorizedSession
from vertexai.generative_models import GenerativeModel


API_TMPL = "https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/publishers/google/models"


def list_publisher_models(project: str, region: str, session: AuthorizedSession) -> List[dict]:
    url = API_TMPL.format(project=project, region=region)
    resp = session.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"List models failed: HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    return data.get("models", [])


def try_generate(model_id: str) -> str:
    model = GenerativeModel(model_id)
    resp = model.generate_content("Say hello in one short sentence.")
    text = getattr(resp, "text", None)
    if text:
        return text.strip()
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
            return joined.strip()
    raise RuntimeError("No text candidates returned from model")


def main() -> int:
    project = os.getenv("PROJECT_ID")
    region = os.getenv("REGION", "us-central1")
    if not project:
        print("[check] PROJECT_ID is not set. export PROJECT_ID and retry.", file=sys.stderr)
        return 2

    # Acquire ADC and an authorized session
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
    except Exception as e:
        print(f"[check] Could not obtain ADC credentials: {e}. Run: gcloud auth application-default login", file=sys.stderr)
        return 2

    print(f"[check] Project={project} region={region}")
    try:
        account = creds.service_account_email if hasattr(creds, "service_account_email") else getattr(creds, "_service_account_email", None)
    except Exception:
        account = None
    try:
        from google.auth.transport.requests import Request as _Req
        creds.refresh(_Req())
        token_info = "ok"
    except Exception as e:
        token_info = f"refresh_failed: {e}"
    print(f"[check] ADC account={account or 'user ADC'} token={token_info}")

    print("[check] Listing google/publisher models…")
    try:
        models = list_publisher_models(project, region, session)
        short = [
            {
                "id": m.get("name", "").split("/models/")[-1],
                "displayName": m.get("displayName"),
                "supportedActions": m.get("supportedActions", {}),
            }
            for m in models
        ]
        # show only gemini-related to keep concise
        gemini = [m for m in short if m["id"].startswith("gemini-")]
        print(json.dumps({"geminiModels": gemini, "totalModels": len(models)}, indent=2))
    except Exception as e:
        print(f"[check] ERROR listing models: {e}", file=sys.stderr)

    # Attempt generation with configured models
    primary = os.getenv("MODEL_ID", "gemini-2.5-flash")
    fallbacks = [m.strip() for m in os.getenv("MODEL_FALLBACKS", "").split(",") if m.strip()]
    candidates = [primary] + [m for m in fallbacks if m != primary]

    any_success = False
    for mid in candidates:
        print(f"[check] Trying generate with model={mid} …")
        try:
            text = try_generate(mid)
            print(f"[check] SUCCESS model={mid}: {text}")
            any_success = True
            break
        except Exception as e:
            print(f"[check] FAILED model={mid}: {e}")
    if not any_success:
        print("[check] No candidate model generated successfully.")
        print("[check] Next steps:\n - Ensure your ADC principal has roles/aiplatform.user on the project\n - Keep REGION=us-central1\n - Try alternate MODEL_ID values that appear in the list above (e.g., gemini-2.5-flash-001)\n - In Cloud Console → Vertex AI → Generative AI Studio, open a Gemini chat to prompt acceptance of terms if required")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
