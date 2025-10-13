# Standing Orders: Minimize Manual Work via Efficient Tool Use

These standing orders describe how Junie (the autonomous programmer) should plan and execute tasks in this repository to minimize manual effort by using the most effective tools and methods available.

Principles
- Prefer specialized tools over generic shell when available (e.g., search tools, file editors, GitHub MCP, Gemini Cloud Assist).
- Keep changes minimal and targeted to satisfy the issue.
- Communicate clearly using status updates (plan + progress) before submitting.
- Run pytest for any change that touches Python runtime or APIs; optional for pure docs but recommended.
- Maintain API contracts covered by tests (see tests/test_chat.py and related files).

Efficient Tool Use
- Code navigation and edits: Use JetBrains IDE features (project search, file structure) and precise edit tools.
- Repository ops: Use GitHub MCP tools for branches, PRs, and reviews when collaboration is needed.
- GCP troubleshooting: Use Gemini Cloud Assist to create investigations with full resource URIs and run analyses; add observations as you gather evidence.
- UI checks: Use Chrome DevTools or Playwright for quick, automated UI interactions when needed.
- Filesystem tasks: Use the filesystem tools to read/write/edit files; avoid ad‑hoc shell scripts unless necessary.

Standard Workflow
1. Plan
   - Define the minimal changes required to satisfy the issue.
   - Choose the most capable tools to reduce manual effort (e.g., automated searches, structured editors).
   - Share/Update the plan via status updates.
2. Investigate
   - Explore the codebase using search and file structure tools.
   - If the issue is an error, create a repro script/test when practical.
3. Implement
   - Make minimal, well‑scoped edits.
   - Keep functions small and readable; preserve response shapes.
4. Verify
   - Run pytest (and any specific repro) to confirm behavior and guard against regressions.
5. Submit
   - Provide a concise summary of changes, and update the plan with final statuses.

Quick Checklist (per task)
- [ ] Clarify the requirement and constraints.
- [ ] Select the most efficient tool(s) for the task.
- [ ] Draft and publish a short plan via status updates.
- [ ] Make minimal edits; keep API contracts stable.
- [ ] Run pytest if code changed (docs optional but recommended).
- [ ] Summarize and submit.

Planning Template
- Goal: <what must be true when done>
- Minimal changes: <smallest viable edits>
- Tools to use: <specialized tools to reduce manual work>
- Risks/edges: <what could break; API contracts>
- Verification: <tests/repros to run>
- Deliverables: <files edited/added, docs updates>
