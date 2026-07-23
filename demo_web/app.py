from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


app = FastAPI(title="Swarm AI QA Browser Demo")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """
    <!doctype html><html><head><title>Browser QA Demo</title></head>
    <body><main><h1>Browser QA Demo</h1>
      <nav>
        <a href="/healthy">Healthy route</a>
        <a href="/broken">Broken route</a>
        <a href="/outbound">Outbound request route</a>
      </nav>
    </main></body></html>
    """


@app.get("/healthy", response_class=HTMLResponse)
async def healthy() -> str:
    return """
    <!doctype html><html><head><title>Healthy checkout</title></head>
    <body><main><h1>Checkout ready</h1><p role="status">All systems operational.</p></main></body></html>
    """


@app.get("/broken", response_class=HTMLResponse)
async def broken() -> str:
    return """
    <!doctype html><html><head><title>Broken checkout</title></head>
    <body><main><h1>Checkout unavailable</h1></main>
    <script>throw new Error('demo checkout initialization failed');</script></body></html>
    """


@app.get("/outbound", response_class=HTMLResponse)
async def outbound() -> str:
    return """
    <!doctype html><html><head><title>Outbound policy demo</title></head>
    <body><main><h1>Outbound policy</h1><img src="https://example.com/tracker.png" alt=""></main></body></html>
    """


@app.get("/api/status")
async def status() -> dict[str, str]:
    return {"status": "ok"}
