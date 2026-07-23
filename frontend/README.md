# QA Director frontend

Next.js App Router frontend for the hackathon control plane. It exposes only the current real
capabilities: public GitHub repository inspection, bounded functional browser journeys,
automated accessibility analysis with axe-core and passive runtime security inspection.
Performance appears as unavailable instead of simulating an agent.

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
