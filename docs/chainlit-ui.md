# Chainlit UI for JaigBot

This guide covers running the Chainlit chat interface locally or as a separate service, how session persistence works, and useful environment switches.

## Overview
- Chainlit provides a lightweight ChatGPT‑like UI that forwards messages to the existing FastAPI POST /chat endpoint.
- The backend does not serve a UI by default; run Chainlit alongside the API during local development or deploy it separately.

## Prerequisites
- FastAPI backend running (see README Quickstart or docs/developer-setup.md).
- Python dependencies: `chainlit` and `httpx`.

Install:
```bash
pip install chainlit httpx
```

## Run locally
1. Start the FastAPI backend (typically at http://localhost:8080).
2. Run Chainlit, pointing it at the backend:
   ```bash
   BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
   ```
3. Open the URL shown in the terminal (usually http://localhost:8000/) to use the chat interface.

## Session persistence (refresh‑safe)
- Chainlit runs server‑side and calls the backend via httpx, so browser cookies issued by the backend are not used in this path.
- To keep your conversation across browser refreshes, the Chainlit app persists a session id in a local file `.chainlit/session_id` and sends it with every /chat call.
- You can override the persisted id:
  ```bash
  export FIXED_SESSION_ID=my-stable-id   # or SESSION_ID
  ```

Caveats for multi‑user deployments:
- The simple persisted id approach will make all users share the same backend session.
- For per‑user isolation, enable authentication in Chainlit and derive a unique, persistent session id per user (e.g., from a login or signed token).

## Tuning long responses and timeouts
- Increase output token cap:
  ```bash
  export MAX_TOKENS=3072
  ```
- Increase Chainlit client timeout for long generations:
  ```bash
  export CHAINLIT_HTTP_TIMEOUT=180  # seconds
  ```

## Model and transport options
- Switch models using `MODEL_ID` (e.g., `gemini-2.5-flash`, `gemini-2.5-flash-001`).
- Transport defaults: REST path is the default (recommended). To switch back to SDK path:
  ```bash
  export USE_VERTEX_REST=false   # default true
  ```
  The REST path calls the official `generateContent` endpoint with `responseMimeType=text/plain`. No `thinking` control field is sent for broad compatibility.

## Auto‑continue (to mitigate truncation)
Auto‑continue is ON by default. Configure via env vars:
```bash
export AUTO_CONTINUE_ON_MAX_TOKENS=false  # default true
export MAX_CONTINUATIONS=2               # number of extra "continue" turns
# Tail‑aware continuations (helps prevent restarts and repetition)
export CONTINUE_TAIL_CHARS=500           # last N chars of previous answer to anchor continuation
export CONTINUE_INSTRUCTION_ENABLED=true # send explicit anti-repetition instruction
export MIN_CONTINUE_GROWTH=10            # min chars the reply must grow per continuation, else stop
```

Notes and tips:
- If responses seem truncated, check /diagnostics and logs. If finishReason=MAX_TOKENS with small visible text but high hidden "thought" tokens, ensure the REST path is used and thinking is disabled (default).

## Deploying Chainlit separately
- You can run Chainlit as a separate Cloud Run service by setting `BACKEND_URL` to the public URL of the FastAPI service.
- For cross‑origin browser calls from a custom frontend, configure CORS on the backend and credentials as needed.
