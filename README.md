# JaigBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Flash)

This repository contains a tiny FastAPI app that serves a minimal web UI and proxies a single message to Vertex AI (Gemini Flash), then displays the single reply.  No auth, no storage, no streaming.

**TL;DR — Where things are:**

- UI in the browser: **GET /** – served from `app/static/index.html`.
- API endpoints:
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`.
  - **GET  /healthz** → simple health check.
- Backend code: `app/main.py` and `app/vertex.py`.
- Run/setup docs: `docs/developer-setup.md` (step‑by‑step).
- Architecture/plan: `docs/plan.md`.

## Running locally

1. Install dependencies (Python 3.11):
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment variables:
   ```bash
   export PROJECT_ID=your-gcp-project-id
   export REGION=us-central1
   export MODEL_ID=gemini-2.5-flash
   ```
3. Start the FastAPI app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```
4. Open http://localhost:8080/ to access the default UI, or see below for the Chainlit UI.

## Chainlit UI (New)

This branch adds a lightweight Chainlit chat interface that replaces the static `index.html`.  Chainlit provides a ChatGPT‑like UI and forwards messages to the existing **/chat** endpoint.

To run the Chainlit UI locally:

1. Ensure the FastAPI backend is running as described above.
2. Install additional dependencies:
   ```bash
   pip install chainlit httpx
   ```
3. Run Chainlit, pointing it at the backend:
   ```bash
   BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
   ```
4. Open the URL shown in the terminal (usually http://localhost:8000/) to use the chat interface.

Notes and tips:
- If responses seem truncated, first check /diagnostics and logs. If finishReason=MAX_TOKENS with very small visible text but high thoughts tokens, the provider may be spending the budget on hidden reasoning tokens. Our REST path disables thinking by default and requests plain text output.
- Increase the output token cap by setting `MAX_TOKENS` (default 2048):
  ```bash
  export MAX_TOKENS=3072
  ```
- If long generations time out in Chainlit, increase the client timeout:
  ```bash
  export CHAINLIT_HTTP_TIMEOUT=180  # seconds
  ```
- You can switch models with `MODEL_ID` (e.g., `gemini-2.5-flash`, `gemini-2.5-flash-001`, or other available IDs).
- Auto-continue is ON by default to mitigate truncated outputs when the model stops due to MAX_TOKENS. You can disable or tune it via env vars:
  ```bash
  export AUTO_CONTINUE_ON_MAX_TOKENS=false  # default true
  export MAX_CONTINUATIONS=2               # number of extra "continue" turns
  # Tail-aware continuations (helps prevent restarts and repetition)
  export CONTINUE_TAIL_CHARS=500           # last N chars of previous answer to anchor continuation
  export CONTINUE_INSTRUCTION_ENABLED=true # send explicit anti-repetition instruction
  export MIN_CONTINUE_GROWTH=10            # min chars the reply must grow per continuation, else stop
  ```
- Transport defaults: We now default to the non‑deprecated REST path (recommended). You can still switch back to the SDK path:
  ```bash
  export USE_VERTEX_REST=false   # default true
  ```
  The REST path calls the official `generateContent` endpoint and requests `responseMimeType=text/plain`. We do not send a `thinking` control field to maintain compatibility across models/versions.

When deployed, you can run Chainlit as a separate Cloud Run service by setting `BACKEND_URL` to the public URL of the FastAPI service. See `chainlit_app.py` for implementation details.


## Conversation memory (session) and persona with Chainlit

The backend now supports lightweight, server-side memory keyed by a `sessionId`, plus optional persona and scene context. The Chainlit client has been updated to:

- Generate a stable `sessionId` per chat and send it in every POST /chat call.
- Optionally send a persona and scene pulled from environment variables.

To use it:

1. Start the FastAPI backend as usual. Memory settings are configurable via env:
   - `MEMORY_ENABLED` (default `true`)
   - `MEMORY_MAX_TURNS` (default `8` user/assistant turns kept)
   - `MEMORY_TTL_SECONDS` (default `3600`)
2. Run Chainlit with optional persona/scene env vars:
   ```bash
   export BACKEND_URL=http://localhost:8080/chat
   export CHARACTER_SYSTEM="Gideon the pansexual giraffe druid — whimsical, kind, lyrical"
   export SCENE_OBJECTIVES="Lead the user through an enchanting savanna quest to craft a song."
   chainlit run chainlit_app.py
   ```

Every message Chainlit sends will include `{ sessionId, character, scene }` so the backend can:
- Persist the last N turns per session in memory and include them in the prompt.
- Persist/update persona/scene for that session and build a system instruction.

You can also supply `sessionId`, `character`, and `scene` directly when calling the `/chat` API yourself.


## Hard-code your character (persona)

If you prefer to hard‑code a character sketch (and optional scene objectives), edit:

- app/persona.py → DEFAULT_CHARACTER and DEFAULT_SCENE

How it’s used:
- Chainlit: On chat start, the client will send CHARACTER_SYSTEM and SCENE_OBJECTIVES from environment if set; otherwise it will fall back to DEFAULT_CHARACTER/DEFAULT_SCENE from app/persona.py.
- Backend: When building the system instruction for a request, the server uses, in order of precedence, session memory → request fields → environment (via client) → app/persona.py defaults.

Override order (highest to lowest):
1. Per‑request fields: POST /chat with { character, scene }
2. Session memory: previously set for that sessionId
3. Environment vars (via Chainlit): CHARACTER_SYSTEM, SCENE_OBJECTIVES
4. Hard‑coded defaults: app/persona.py DEFAULT_CHARACTER / DEFAULT_SCENE

To disable the hard‑coded defaults, set the strings to "" in app/persona.py.

You can inspect the effective defaults and memory via GET /config and GET /diagnostics.
