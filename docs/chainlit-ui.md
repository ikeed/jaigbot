# Chainlit UI for AIMSBot

This guide covers running the Chainlit chat interface locally or as a separate service, how session persistence works, and useful environment switches.

## Overview
- Chainlit provides a lightweight ChatGPT‑like UI that forwards messages to the existing FastAPI POST /chat endpoint.
- The backend does not serve a UI by default; run Chainlit alongside the API during local development or deploy it separately.

## Code map

| Concern | Module |
|---------|--------|
| Chainlit entry point | `chainlit_app.py` |
| Startup and session wiring | `app/services/chainlit/orchestrator.py` |
| Message/avatar rendering | `app/services/chainlit/ui_handler.py` |
| Backend calls — hits the FastAPI `/chat` endpoint over HTTP even when running in the same process under `run_app.py` | `app/services/chainlit/backend_client.py` |
| Chainlit data layer backed by the app memory store | `app/chainlit_memory_data_layer.py` |
| Per-user current-thread pointer | `app/chainlit_thread_state.py` |

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
- Chainlit uses a custom data layer backed by the app memory store. This lets Chainlit restore the visible thread after browser refreshes and Cloud Run instance restarts.
- For new conversations, the Chainlit thread id is also used as the backend `sessionId`, so the UI thread and backend persona/history share one durable key.
- The app does not store a separate per-user "latest backend session id" pointer. It stores only a current Chainlit thread pointer so a plain `/chat` refresh can redirect to `/chat/thread/<thread_id>` and let Chainlit resume the actual thread.
- Local development can persist this store with:
  ```bash
  export MEMORY_PERSIST_PATH=.chainlit/session_memory.json
  ```
- Production Cloud Run deployments should use `MEMORY_BACKEND=redis` with Google Memorystore so multiple instances share the same Chainlit thread and backend session state.
- You can override the backend session id:
  ```bash
  export FIXED_SESSION_ID=my-stable-id   # or SESSION_ID
  ```

Caveats for multi‑user deployments:
- Do not use `FIXED_SESSION_ID` or `SESSION_ID` in multi-user deployments; those intentionally force a shared backend session id.
- Normal authenticated Chainlit use isolates threads by Chainlit user and thread id.
- Older stored threads may still contain `metadata.session_id` from the previous two-id implementation. The resume path keeps those readable, but new conversations should not create that shape.
- New Chat and Logout clear the current-thread pointer; the next `/chat` load is therefore a new Chainlit thread and a new backend session.

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
- Switch the main reply model using `MODEL_ID` (e.g., `gemini-3.6-flash`).
- Switch the AIMS classifier separately using `AIMS_CLASSIFIER_MODEL_ID`
  (e.g., `gemini-3.5-flash-lite`) and tune classifier thinking with
  `AIMS_CLASSIFIER_THINKING_LEVEL` (`minimal`, `low`, `medium`, or `high`).
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
