# Deterministic browser target

Local-only target containing a healthy route, a JavaScript failure, a cross-origin request and
an interactive route. The interactive fixture includes a safe internal link and GET search form,
plus logout, a sensitive-field form and a purchase POST that the Browser policy must omit. It
exists to exercise screenshots, traces, functional-flow evidence and safety blocks without
relying on an external website.

```powershell
python -m uvicorn demo_web.app:app --port 8010
```
