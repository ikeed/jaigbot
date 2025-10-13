# MCP Empowerment and Available Tools

This project is now wired up to a broad set of MCP services that Junie can use during development and troubleshooting. This page lists the tools, what they are for, and how they fit into JaigBot’s workflow.

Note: These tools are available to Junie (the autonomous programmer) in the IDE/agent environment. They do not change the runtime behavior of the FastAPI backend or Chainlit UI, unless we explicitly modify the codebase.

## Principles
- Minimal, targeted changes to code to satisfy issues.
- Always run pytest before submitting changes that affect Python runtime behavior.
- Prefer specialized tools over generic shell when available.
- Keep the user informed using the status update tool (plan and progress).

## Available MCP Services

1. GitHub
   - Capabilities: Manage issues, PRs, branches, commits; request code reviews.
   - Usage in this repo: Create or update issues/PRs for changes, request reviews, or automate routine chores.

2. Gemini Cloud Assist (GCP Troubleshooting)
   - Capabilities: Create investigations, run analyses, add observations, search and analyze GCP resources (non‑metrics, non‑BigQuery).
   - Usage: Troubleshoot Cloud Run, Vertex AI access/config, or GCP misconfigurations by creating an investigation with project/resource URIs.

3. Notion
   - Capabilities: Read/write pages, databases, comments.
   - Usage: Update or create workspace docs, design notes, or runbooks if this repo is linked to a Notion workspace.

4. Filesystem (Local)
   - Capabilities: Read/write files, list directories, move/rename, edit content.
   - Usage: Manipulate files in this project directory to implement fixes or write docs; keep edits minimal and tested.

5. Sequential Thinking
   - Capabilities: Step‑by‑step reasoning assistant for complex tasks.
   - Usage: Plan changes, refine approaches, and validate solution hypotheses before editing code.

6. Chrome DevTools / Playwright
   - Capabilities: Browser automation and debugging; navigate UIs, take actions, validate behavior.
   - Usage: Validate Chainlit UI flows or backend Swagger if needed; not required for standard unit tests.

7. Firebase
   - Capabilities: Manage Firebase projects and apps, initialize services, retrieve SDK configs.
   - Usage: Only if the project adopts Firebase for any auxiliary features (not required for core JaigBot backend).

8. Cloud Run
   - Capabilities: List GCP projects; assist with Cloud Run deployment workflows.
   - Usage: Validate Cloud Run environments and deployments alongside terraform/CI configuration.

9. Vectorize
   - Capabilities: Vector database operations (search, upsert, manage namespaces).
   - Usage: Optional future enhancement; not used by default in JaigBot runtime.

10. JetBrains IDE Features
   - Capabilities: Code search and structure, navigate/open files, edit files with precision.
   - Usage: Preferred for exploring project structure and applying minimal, safe changes.

## How Junie uses these in JaigBot
- Code changes under `app/` or `chainlit_app.py` → run `pytest` locally; keep API contracts stable (tests cover `POST /chat`, error shapes, and AIMS coaching flows).
- Docs‑only changes → tests optional but recommended.
- Infrastructure changes → consult `terraform/README.md`; CI and WIF are configured there.
- Vertex AI issues → prefer offline test coverage first; for live environment concerns use Gemini Cloud Assist investigation flow.
- Status updates → Junie posts plan and progress updates before submitting.

## Quick Links
- Developer Setup: docs/developer-setup.md
- API reference: docs/api.md
- Chainlit UI: docs/chainlit-ui.md
- Health checks: docs/health-checks.md
- Memory/persona: docs/memory-and-persona.md
- Terraform: terraform/README.md
