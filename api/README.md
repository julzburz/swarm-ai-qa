# FastAPI control plane

Primer corte vertical sobre el orquestador existente. Expone validacion y preview de planes,
creacion y consulta de runs, cancelacion, historial durable y streaming SSE.

## Inicio local

```powershell
python -m pip install -r requirements-dev.txt
python -m uvicorn api.app:create_app --factory --reload
```

OpenAPI queda disponible en `http://127.0.0.1:8000/docs`.

Con `SWARM_STORAGE_BACKEND=auto`, la API usa Neon cuando existe `DATABASE_URL` y SQLite
cuando no existe. También puede forzarse `neon` o `sqlite`. La ruta SQLite predeterminada es
`.data/swarm-ai-qa.db` y puede cambiarse con `SWARM_SQLITE_PATH`; `.data/` no se versiona.

Al iniciar con Neon, la API comprueba la conexión y la existencia de las tablas necesarias.
`GET /healthz` informa únicamente si el storage activo es `neon` o `sqlite`, sin exponer
hostnames, usuarios ni credenciales.

## Autenticación e historial

Si `SWARM_API_KEY` contiene al menos 32 caracteres, todas las rutas `/v1/*` exigen
`Authorization: Bearer <clave>`. `/healthz` permanece público y solo informa si la protección
Bearer está activa. La clave nunca se devuelve en respuestas ni logs.

`GET /v1/runs?limit=20&offset=0` lista ejecuciones persistidas, ordenadas por su actualización
más reciente. QA Director consume este endpoint para reabrir análisis conservados en Neon.

## Resultados y artifacts

- `GET /v1/runs/{run_id}/findings` devuelve findings correlacionados y permite filtrar por
  `domain`, `severity`, `limit` y `offset`.
- `GET /v1/runs/{run_id}/artifacts` cataloga evidencia local y referencias externas sin exponer
  rutas del filesystem.
- `GET /v1/runs/{run_id}/artifacts/{artifact_id}` descarga solamente evidencia materializada
  que pertenece al run y cuyo SHA-256 coincide con la referencia persistida.

Los IDs de descarga son hashes opacos de la URI interna. El servidor no acepta rutas de archivo
del cliente, valida que el archivo resuelva dentro de `SWARM_ARTIFACT_ROOT` y protege todos estos
endpoints con el mismo Bearer opcional de `/v1/*`.

## Flujo seguro

1. Enviar una `UserMissionRequestV1` a `POST /v1/plans/preview`.
2. Revisar plan, restricciones y `missing_executors`.
3. Conectar executors reales mediante `create_app(registry=...)`.
4. Enviar `{ "mission": ..., "approved": true }` a `POST /v1/runs`.
5. Consultar el estado o suscribirse a `/events/stream`.

La aplicacion por defecto no registra executors demo. Si falta alguno, responde `503`
con la lista exacta; nunca presenta actividad o resultados ficticios.

## GitHub read-only slice

La factory GitHub registra executors reales para Repository Analyst, Test Architect y
Evidence Reporting Analyst:

```powershell
python -m uvicorn api.github_factory:create_github_app --factory --reload
```

Los repositorios publicos no requieren token y nunca reciben el token privado del servidor.
Para repositorios privados, definir `GITHUB_TOKEN` con permiso fine-grained `Contents: read`
y agregar cada ID canonico `github:OWNER/REPO` a
`SWARM_GITHUB_ALLOWED_PRIVATE_REPOSITORIES`. El adapter solo realiza `GET`.

Este primer slice ejecuta misiones cuyo unico dominio es `repository`. Si la mision solicita
security, browser, API, performance o accessibility, el preflight devolvera los executors que
aun faltan.

## GitHub + Playwright + axe automation

La factory compuesta agrega Browser Automation Engineer, Accessibility Specialist y Security
Test Engineer para misiones runtime:

```powershell
python -m playwright install chromium
python -m uvicorn api.automation_factory:create_automation_app --factory --reload
```

El worker navega solamente los journeys seleccionados por Test Architect dentro de
`runtime_target.allowed_paths`. Bloquea rutas declaradas en `blocked_paths`, origenes externos,
metodos distintos de `GET/HEAD` y destinos localhost, privados, link-local, reservados o de
metadata. Los subrecursos del mismo origen usan una politica separada para no confundir rutas
navegables con CSS, JavaScript o endpoints necesarios. Los screenshots y traces se escriben
bajo `.data/artifacts/`.

Accessibility ejecuta axe-core sobre las mismas rutas permitidas y conserva un JSON redactado
con versión, reglas, selectores y resultados. Reporting correlaciona cada finding axe con la
navegación Playwright de la misma URL, pero declara pendientes teclado, lector de pantalla,
zoom/reflow y estados que requieren interacción. `npm install` dentro de `frontend/` instala la
versión fijada de axe-core; `SWARM_AXE_SCRIPT_PATH` permite usar otra ubicación del script.

Security ejecuta una auditoria HTTP pasiva sobre las rutas permitidas. Observa HTTPS/TLS,
cabeceras defensivas, CORS y atributos de cookies sin conservar sus valores. Usa solicitudes
`GET` acotadas, bloquea redirects fuera del origen o allowlist y no realiza fuzzing,
explotacion, autenticacion ni cambios en el target.
