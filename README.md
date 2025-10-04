# JaigBot

This repository contains a tiny FastAPI app that serves as a minimal backend to call Vertex AI (Gemini Flash) and display the reply.  It also includes a new chat interface built with Chainlit.

## FastAPI backend (existing)

The FastAPI service exposes:

- **GET /** — serves the original static HTML UI from `app/static/index.html`.
- **POST /chat** — proxies a single message to Vertex AI and returns `{ reply, model, latencyMs }`.
- **GET /healthz** — simple health check.

The backend code lives in `app/main.py` and `app/vertex.py`.

### Running locally

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Set the required environment variables:

   - `PROJECT_ID` – your GCP project
   - `REGION` – e.g. `us-central1`
   - `MODEL_ID` – e.g. `gemini-1.5-flash`
   - `GOOGLE_APPLICATION_CREDENTIALS` – path to your service‑account JSON
   - any others required by Vertex AI

3. Start the server:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8080
   ```

4. Visit [http://localhost:8080](http://localhost:8080/) to use the original UI.

### Deploying to Cloud Run

CI/CD workflows and Terraform scripts are provided to deploy the FastAPI service to Cloud Run; see `.github/workflows/deploy.yml` and `terraform/`.

## Chainlit UI (new)

This branch adds a modern chat UI using [Chainlit](https://www.chainlit.io/).  The Chainlit app lives in `chainlit_app.py` and forwards each user message to your backend.  To try it:

1. Ensure the backend is running (locally or on Cloud Run) and note its `/chat` endpoint.
2. Install dependencies (includes `chainlit` and `httpx`):

   ```bash
   pip install -r requirements.txt
   ```

3. Set the `BACKEND_URL` environment variable to your backend's `/chat` endpoint.  For local development:

   ```bash
   export BACKEND_URL=http://localhost:8080/chat
   ```

   When using Cloud Run, set it to something like `https://aimsbot-911779552073.us-central1.run.app/chat`.

4. Start Chainlit:

   ```bash
   chainlit run chainlit_app.py
   ```

5. Open [http://localhost:8000](http://localhost:8000/) to use the chat UI.  Messages you send will be forwarded to `BACKEND_URL` and the replies streamed back.

You can deploy the Chainlit UI as a separate service (e.g. on Cloud Run) and simply configure the `BACKEND_URL` environment variable to point at your FastAPI backend.
