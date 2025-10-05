# API Reference

This document describes all HTTP endpoints exposed by the JaigBot FastAPI service.

Base URL (local development):
- http://localhost:8080

Base URL (Cloud Run):
- https://YOUR_SERVICE-<hash>-uc.a.run.app (replace with your deployed URL)

Content Type:
- All request/response bodies are JSON unless noted.
- Use header: Content-Type: application/json for POST requests.

Authentication:
- No app-level authentication is enforced by default. Upstream Vertex AI calls require valid Google ADC on the server side.

Auto-generated API docs (from FastAPI):
- Swagger UI: GET /docs
- ReDoc: GET /redoc
- OpenAPI schema: GET /openapi.json

---

## GET /
Serves the static single-page UI.

- Description: Returns app/static/index.html.
- Response: HTML page.
- Status Codes:
  - 200 OK

Example:
- curl -sS http://localhost:8080/

---

## GET /healthz
Lightweight health check.

- Description: Returns a simple status payload; does not call Vertex AI.
- Response Body:
  {
    "status": "ok"
  }
- Status Codes:
  - 200 OK

Example:
- curl -sS http://localhost:8080/healthz

---

## POST /chat
Send a single message; the server calls Vertex AI (Gemini Flash) and returns a single reply.

- Description: Proxies the message to Vertex AI using environment configuration.
- Request Body (application/json):
  {
    "message": "string (required, min length 1, max ~2KiB)"
  }
- Response Body (success 200):
  {
    "reply": "string",
    "model": "string",
    "latencyMs": number
  }
- Error Responses:
  - 400 Bad Request
    - Invalid UTF-8 in message
    - Message too large (max 2 KiB)
  - 404 Not Found (Model not found or access denied)
    - Shape:
      {
        "error": {
          "message": "Publisher model not found or access denied. Verify MODEL_ID and REGION; ensure Vertex AI API is enabled, billing is active, and your ADC principal has roles/aiplatform.user. You may set MODEL_FALLBACKS to try alternatives.",
          "code": 404,
          "requestId": "...",
          "upstream": "..."  // only if EXPOSE_UPSTREAM_ERROR=true
        }
      }
  - 500 Internal Server Error
    - Missing configuration or unexpected failure. Shape:
      {
        "error": { "message": "Internal server error", "code": 500, "requestId": "..." }
      }
  - 502 Bad Gateway (Upstream error calling Vertex AI)
    - Shape:
      {
        "error": {
          "message": "Upstream error calling Vertex AI",
          "code": 502,
          "requestId": "...",
          "upstream": "..."  // only if EXPOSE_UPSTREAM_ERROR=true
        }
      }
- Headers:
  - x-request-id is set on the response for correlation.
- Notes:
  - Environment variables used: PROJECT_ID, REGION (default us-central1), MODEL_ID (default gemini-2.5-flash), TEMPERATURE (default 0.2), MAX_TOKENS (default 256).
  - Optional: MODEL_FALLBACKS (comma-separated) to try alternative models if the primary returns 404 (e.g., "gemini-2.5-flash-001").
  - To include upstream error details in 502/404 JSON, set EXPOSE_UPSTREAM_ERROR=true.
  - See /config to inspect runtime configuration.

Examples:
- curl -sS -X POST http://localhost:8080/chat \
    -H 'Content-Type: application/json' \
    -d '{"message":"Hello!"}'

---

## GET /config
Return non-sensitive runtime configuration to aid local troubleshooting.

- Description: Exposes current values for projectId, region, model, logging flags, etc.
- Response Body:
  {
    "projectId": "string|null",
    "region": "string",
    "modelId": "string",
    "temperature": number,
    "maxTokens": number,
    "logLevel": "string",
    "logHeaders": boolean,
    "logRequestBodyMax": number,
    "allowedOrigins": ["string", ...],
    "exposeUpstreamError": boolean
  }
- Status Codes:
  - 200 OK

Example:
- curl -sS http://localhost:8080/config

---

## Static files

- GET /static/* → serves files from app/static/ (e.g., /static/index.html, images, CSS, JS).
- Status Codes: 200 OK on success; 404 if not found.

---

## CORS

- Disabled by default. If ALLOWED_ORIGINS env var is set to a comma-separated list, CORS is enabled for those origins for POST/OPTIONS with the Content-Type header.

---

## Environment variables reference (server-side)

- PROJECT_ID (required for /chat): Google Cloud project ID. If unset, /chat returns a 500 error.
- REGION: Vertex AI region (default: us-central1).
- MODEL_ID: Model ID (default: gemini-2.5-flash).
- TEMPERATURE: Generation temperature (default: 0.2).
- MAX_TOKENS: Max output tokens (default: 256).
- LOG_LEVEL: Logging level (default: info).
- LOG_HEADERS: If true, request headers are logged with common sensitive values redacted (default: false).
- LOG_REQUEST_BODY_MAX: Max bytes of body logged in middleware (default: 1024).
- ALLOWED_ORIGINS: Comma-separated list to enable CORS (default: empty/off).
- EXPOSE_UPSTREAM_ERROR: If true, includes upstream Vertex error text in the 502 JSON for /chat (default: false).

---

## OpenAPI/SDK generation

The service exposes its OpenAPI schema at /openapi.json, which you can use to generate clients or import into tools like Postman/Insomnia.


---

## GET /models
List available publisher models from google in your project+region using the server's ADC.

- Description: Calls Vertex AI REST to list models at publishers/google and returns a simplified list.
- Response Body:
  {
    "models": [
      { "id": "gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "supportedActions": { ... } },
      ...
    ],
    "count": number,
    "region": "us-central1"
  }
- Status Codes:
  - 200 OK on success
  - 502 if the list call failed upstream
  - 500 on unexpected server errors
- Notes:
  - Useful for diagnosing 404 model errors. If the model you configured is not in this list, pick one that is (e.g., gemini-2.5-flash) or resolve IAM/access in Google Cloud Console.

Example:
- curl -sS http://localhost:8080/models | jq '.'
