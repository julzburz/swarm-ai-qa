# QA Director frontend

Next.js App Router frontend for the hackathon control plane. It exposes only the current real
capabilities: public GitHub repository inspection and bounded functional browser journeys.
Security, accessibility and performance appear as unavailable instead of simulating agents.

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

Open `http://localhost:3000`. Next.js proxies `/control-plane/*` to
`SWARM_CONTROL_PLANE_URL`, defaulting to `http://127.0.0.1:8000`. This server-side setting is
not exposed as a `NEXT_PUBLIC_` variable and must never contain credentials.
