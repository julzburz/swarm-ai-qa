# Deterministic browser target

Local-only target containing a healthy route, a JavaScript failure and a cross-origin request.
It exists to exercise screenshots, traces, page-error capture and network policy without relying
on an external website.

```powershell
python -m uvicorn demo_web.app:app --port 8010
```
