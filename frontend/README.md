# QA Director frontend

Next.js App Router frontend for the hackathon control plane. It exposes only the current real
capabilities: public GitHub repository inspection, bounded functional browser journeys,
automated accessibility analysis with axe-core, passive runtime security inspection and
isolated single-user performance smoke measurements.

Completed runs include Test Design Studio: a compact risk-linked matrix with preconditions,
steps, expected results and Spanish BDD/Gherkin. Automated cases receive only evidence-backed
statuses; negative, keyboard, authenticated and UAT cases remain visibly `manual_required`.

For staging and sandbox targets, QA Director exposes an explicit **Flujos funcionales seguros**
option. It permits only bounded same-origin link clicks and GET forms filled with synthetic,
non-sensitive values. Production disables the option. The report shows executed links, fields,
GET submissions and blocked interactions, while confirming that mutating requests and destructive
actions were not allowed.

## Run locally

Start the FastAPI automation factory from the project root:

```powershell
python -m uvicorn api.automation_factory:create_automation_app --factory --reload
```

Then start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. A server-side Route Handler proxies `/control-plane/*` to
`SWARM_CONTROL_PLANE_URL`, defaulting to `http://127.0.0.1:8000`. If FastAPI uses
`SWARM_API_KEY`, copy the same secret to `SWARM_CONTROL_PLANE_API_KEY` in `frontend/.env.local`.
The proxy adds the Bearer header server-side, including for SSE, so the browser never receives
the key. Neither variable may use the `NEXT_PUBLIC_` prefix.

The left rail loads recent persisted runs and can reopen their state, events and final evidence.
Accessibility can be selected alone or with Browser Functional; the report shows automated
coverage and the manual criteria that were not verified.
Security can be selected for runtime targets and reports HTTPS/TLS, response-header, cookie and
CORS signals. It uses allowlisted `GET` requests only, redacts cookie values and never exploits
the evaluated application.
Performance can be selected for a runtime target. It runs three cold Chromium contexts per
allowlisted route and reports lab LCP, CLS, TTFB, loading, transfer and resource metrics. It
never performs load or stress testing, does not measure INP, and does not label a signal as a
regression without an explicit baseline.

Completed reports also load the run artifact catalog. Materialized evidence can be downloaded
through the server-side `/control-plane` proxy, so an enabled API key remains outside the
browser and internal filesystem paths are never rendered.
