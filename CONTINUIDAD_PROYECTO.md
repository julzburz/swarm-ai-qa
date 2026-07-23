# Continuidad del proyecto Swarm AI QA

Ultima actualizacion: 23 de julio de 2026 (America/La_Paz).

Este archivo sirve como punto de reanudacion en otra computadora. El PRD sigue siendo la
fuente principal de intencion y los ADR prevalecen sobre decisiones anteriores.

## Estado actual

La fundacion ejecutable incluye:

- contratos Pydantic estrictos para misiones, planes, especialistas, evidencia y releases;
- perfiles YAML de 14 agentes con limite permanente de QA read-only;
- planificador determinista `RuleBasedQaDirector`;
- scheduler asincrono con dependencias, paralelismo, retries y cancelacion;
- historial de eventos y suscripcion en vivo;
- stores compatibles para SQLite local y Neon PostgreSQL;
- control plane FastAPI inicial;
- adapter GitHub REST estrictamente read-only;
- executors reales para Repository Analyst, Test Architect y Evidence Reporting Analyst;
- worker Playwright con navegacion y red acotadas;
- executor real de Browser Automation Engineer;
- aplicacion web demo local y determinista;
- frontend Next.js de QA Director conectado al control plane;
- deteccion de monorepos y componentes con impacto de cambio por componente;
- seleccion automatica y persistencia durable en Neon con fallback SQLite;
- 54 pruebas automatizadas verdes.

La carpeta no estaba inicializada como repositorio Git al realizar esta actualizacion. Si se
trabaja mediante una carpeta sincronizada, verificar que todos los archivos hayan terminado
de sincronizar antes de cambiar de computadora. No copiar ni publicar `.env` con secretos.

## Actualizacion implementada: FastAPI control plane

Se agrego el paquete `api/` con estos endpoints:

| Metodo | Ruta | Funcion |
|---|---|---|
| `GET` | `/healthz` | Salud y version del servicio |
| `POST` | `/v1/plans/preview` | Valida una mision y genera su plan |
| `POST` | `/v1/runs` | Acepta una ejecucion aprobada |
| `GET` | `/v1/runs/{run_id}` | Devuelve el checkpoint actual |
| `POST` | `/v1/runs/{run_id}/cancel` | Solicita cancelacion segura |
| `GET` | `/v1/runs/{run_id}/events` | Historial JSON desde una secuencia |
| `GET` | `/v1/runs/{run_id}/events/stream` | Eventos Server-Sent Events (SSE) |

Decisiones de seguridad:

- un plan que requiere aprobacion no arranca hasta recibir `approved: true`;
- se comprueba que todos los agentes seleccionados tengan executor antes de aceptar el run;
- la aplicacion por defecto no instala executors falsos ni inventa actividad;
- si faltan executors, la API responde `503` con sus IDs exactos;
- el cierre de la aplicacion solicita cancelacion de runs activos;
- SQLite se usa localmente en `.data/swarm-ai-qa.db` y queda excluido por `.gitignore`.

## Actualizacion implementada: GitHub read-only vertical slice

Se agrego una segunda factory de FastAPI que registra tres executors reales:

```text
GitHub repository/PR
  -> repository_analyst
  -> test_architect
  -> evidence_reporting_analyst
  -> QaRunReportV1 dentro del checkpoint del run
```

El adapter GitHub realiza exclusivamente solicitudes HTTP `GET` para:

- metadata del repositorio;
- commit de la rama predeterminada;
- arbol Git recursivo y acotado;
- manifests, lockfiles y configuracion CI seleccionados;
- metadata y archivos cambiados de un pull request opcional.

Limites de seguridad actuales:

- timeout de 15 segundos;
- dos reintentos para red, rate limiting y fallos transitorios 5xx;
- maximo 32 manifests/configuraciones y 128 KiB por archivo;
- maximo 10 paginas o 1000 archivos de un pull request;
- sin redirects y sin endpoints de escritura;
- los repositorios publicos nunca reciben el token privado del servidor;
- repositorios privados requieren `GITHUB_TOKEN` con `Contents: read` y su ID canonico en
  `SWARM_GITHUB_ALLOWED_PRIVATE_REPOSITORIES`;
- `owner`, `name`, `repository_id` y `clone_url` deben identificar el mismo repositorio GitHub.

La version REST enviada en `X-GitHub-Api-Version` es `2026-03-10`, verificada contra la
documentacion oficial vigente de GitHub el 22 de julio de 2026.

## Actualizacion implementada: Browser Automation con Playwright

La factory compuesta permite ejecutar misiones GitHub read-only y misiones runtime del dominio
`functional`:

```text
Runtime target allowlisted
  -> test_architect
  -> browser_automation_engineer
  -> evidence_reporting_analyst
  -> QaRunReportV1 + screenshots + trace
```

El worker Playwright implementa:

- aislamiento por `BrowserContext` y service workers bloqueados;
- navegacion unicamente al mismo origen;
- allowlist y blocklist por prefijo de ruta;
- bloqueo de localhost, IP privadas, link-local, reservadas y metadata, incluyendo resolucion DNS;
- politica separada para navegacion y subrecursos del mismo origen;
- bloqueo de metodos distintos de `GET/HEAD`;
- presupuesto maximo de solicitudes;
- timeout de navegacion y operaciones;
- captura de screenshot por ruta y un `trace.zip` por tarea;
- observacion de errores de consola, excepciones de pagina y fallos de red;
- eliminacion de query strings en URLs registradas y redaccion basica de secretos en texto;
- hashes SHA-256 y referencias `artifact://browser/...`;
- findings funcionales para journeys fallidos;
- version de Playwright y Chromium dentro de `ToolExecutionResultV1`.

## Actualizacion implementada: seguridad de targets y correlacion del enjambre

El flujo combinado ahora conserva dependencias directas entre todos los agentes:

```text
Repository Analyst
  -> Test Architect
  -> Browser Automation Engineer
  -> Evidence Reporting Analyst recibe Repository + Architecture + Browser
```

- Test Architect selecciona los journeys permitidos que Browser debe ejecutar;
- Browser rechaza cualquier journey que no pertenezca al allowlist aprobado;
- Reporting conserva evidencia GitHub y Browser en el mismo informe;
- los findings Browser se correlacionan con el perfil o cambio GitHub de la mision;
- el reporte declara expresamente que no existe causalidad ruta-a-codigo mientras no haya
  un mapa de rutas y componentes que la demuestre;
- repositorios publicos no pueden provocar que el servidor envie su token GitHub;
- repositorios privados necesitan token y allowlist del servidor;
- targets runtime internos se rechazan antes de lanzar Chromium.

## Actualizacion implementada: inteligencia multicomponente y QA Director UI

Repository Analyst ya no consolida obligatoriamente todo bajo `root`:

- usa manifests capturados para identificar raices de componentes;
- separa lenguajes, frameworks, runtimes y test frameworks por directorio;
- conserva cada comando descubierto con su `working_directory`;
- clasifica perfiles con varios componentes como `monorepo`;
- agrupa archivos de un pull request por componente afectado;
- deriva rutas candidatas solamente desde convenciones verificables de Next.js App Router y
  Pages Router;
- Test Architect prioriza esas rutas si tambien pertenecen al allowlist runtime;
- rutas dinamicas sin valores concretos no se inventan.

Se agrego `frontend/`, una aplicacion Next.js App Router + TypeScript:

- permite seleccionar repositorio, runtime o ambos;
- ofrece trabajo rapido de uno o dos encargos y examen de todas las areas conectadas;
- muestra como no disponibles los especialistas que aun no tienen executor;
- previsualiza agentes, restricciones, requests y duracion antes de aprobar;
- inicia runs reales y consume el stream SSE del control plane;
- muestra estado real por agente, eventos, componentes detectados, findings y correlacion;
- no incluye modo mock ni actividad ficticia;
- usa un rewrite server-side `/control-plane/*`, por lo que no expone la URL interna ni secretos
  como variables `NEXT_PUBLIC_*`.

Los artefactos se escriben bajo `SWARM_ARTIFACT_ROOT`, cuyo valor predeterminado es
`.data/artifacts`. Nunca se escriben dentro del repositorio evaluado.

## Actualizacion implementada: persistencia automática en Neon

La API selecciona el store mediante `SWARM_STORAGE_BACKEND`:

- `auto` usa Neon si existe `DATABASE_URL` y SQLite si no existe;
- `neon` exige una conexión Neon configurada;
- `sqlite` fuerza el checkpoint local en `.data/`.

Al iniciar con Neon, el backend comprueba la conexión y las tablas `runs`, `run_tasks` y
`run_events`. El endpoint `/healthz` muestra solamente el tipo de storage, sin revelar datos de
conexión. Se validó una ejecución real de un repositorio público de GitHub, se cerró el store y
se confirmó que la API restauró el mismo run completado después del reinicio.

## Archivos agregados o modificados

- `api/app.py`: factory de FastAPI, rutas, JSON y SSE.
- `api/controller.py`: ciclo de vida de tareas asincronas y preflight de executors.
- `api/config.py`: configuracion minima desde entorno.
- `api/schemas.py`: contratos HTTP del primer corte.
- `api/README.md`: instrucciones breves del modulo.
- `api/github_factory.py`: factory con los tres executors GitHub reales.
- `api/automation_factory.py`: factory compuesta GitHub + Browser.
- `adapters/github/`: cliente REST, modelos internos y limites read-only.
- `workers/browser/`: puerto, modelos y worker Playwright.
- `executors/repository.py`: perfil tecnologico, contexto e impacto de PR.
- `executors/test_architect.py`: estrategia y cobertura basadas en evidencia.
- `executors/browser.py`: conversion de capturas en evidencia, journeys y findings.
- `executors/reporting.py`: reporte final sin inventar findings.
- `executors/factory.py`: registro explicito del primer enjambre ejecutable.
- `demo_web/`: objetivo local determinista sano, roto y con solicitud externa.
- `tests/test_api.py`: seis pruebas del control plane.
- `tests/test_github_slice.py`: cliente HTTP y run GitHub completo con fixtures.
- `tests/test_browser_worker.py`: politica, Chromium real y run runtime completo.
- `frontend/`: QA Director Next.js, formulario de mision, preview, SSE y reporte.
- `requirements.txt`: FastAPI y Uvicorn.
- `requirements-dev.txt`: dependencias de desarrollo y pruebas.
- `.env.example`: selección de storage y fallback `SWARM_SQLITE_PATH`.
- `.gitignore`: exclusion de `.data/`.

## Preparar otra computadora

Requisitos recomendados:

- Python 3.11 o posterior;
- Node.js 20.9 o posterior;
- PowerShell, Bash o una terminal equivalente;
- copia completa de esta carpeta;
- credenciales propias recreadas localmente si se usara Neon.

En PowerShell:

```powershell
cd "RUTA_AL_PROYECTO"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python -m uvicorn api.automation_factory:create_automation_app --factory --reload
```

En otra terminal:

```powershell
cd "RUTA_AL_PROYECTO\frontend"
npm install
npm run dev
```

En Bash:

```bash
cd /ruta/al/proyecto
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python -m uvicorn api.automation_factory:create_automation_app --factory --reload
```

En otra terminal:

```bash
cd /ruta/al/proyecto/frontend
npm install
npm run dev
```

Abrir despues:

- OpenAPI/Swagger: `http://127.0.0.1:8000/docs`
- health check: `http://127.0.0.1:8000/healthz`
- QA Director: `http://localhost:3000`

## Ejemplo de mision GitHub ejecutable

```json
{
  "objective": "Inspeccionar estructura e impacto del pull request",
  "mode": "quick_task",
  "repository_target": {
    "repository_id": "github:OWNER/REPO",
    "owner": "OWNER",
    "name": "REPO",
    "clone_url": "https://github.com/OWNER/REPO.git",
    "private": false
  },
  "pull_request_number": 123,
  "requested_jobs": [
    {
      "objective": "Crear un perfil del repositorio respaldado por evidencia",
      "domains": ["repository"]
    }
  ]
}
```

Reemplazar `OWNER`, `REPO` y `123`. Si no se necesita analizar un PR, omitir
`pull_request_number`. Enviar el cuerpo a `POST /v1/plans/preview`; con la factory GitHub,
`executable` debe ser `true` para una mision limitada al dominio `repository`.

Para arrancar un run, `POST /v1/runs` recibe:

```json
{
  "mission": {
    "objective": "Inspeccionar un repositorio publico",
    "mode": "quick_task",
    "repository_target": {
      "repository_id": "github:octocat/Hello-World",
      "owner": "octocat",
      "name": "Hello-World",
      "clone_url": "https://github.com/octocat/Hello-World.git",
      "private": false
    },
    "requested_jobs": [
      {
        "objective": "Crear perfil tecnologico",
        "domains": ["repository"]
      }
    ]
  },
  "approved": true
}
```

Este request es aceptado por `api.github_factory:create_github_app`. Misiones que tambien
soliciten security, browser, API, performance o accessibility devolveran `503` hasta que sus
executors reales sean implementados.

## Verificacion realizada

Comando ejecutado:

```text
python -m unittest discover -s tests -v
```

Resultado al 22 de julio de 2026:

```text
Ran 54 tests
OK
```

Cobertura funcional de las nuevas pruebas:

- health y OpenAPI;
- selección automática SQLite/Neon y fallo seguro sin credenciales;
- persistencia y restauración de un run mediante la API después de reiniciar el store;
- preview y deteccion de executors ausentes;
- aprobacion explicita obligatoria;
- rechazo seguro cuando faltan executors;
- ejecucion completa, consulta de estado, historial y SSE;
- cancelacion de un run activo.
- uso exclusivo de `GET` y header de version GitHub;
- repositorios privados rechazados antes de acceder a red cuando falta token;
- repositorios privados rechazados cuando no estan en el allowlist del servidor;
- repositorios publicos inspeccionados sin enviar el token del servidor;
- rechazo de identificadores GitHub inconsistentes o con segmentos de ruta;
- retry de errores GitHub transitorios;
- deteccion de TypeScript, Next.js, React y Jest desde evidencia;
- run completo Repository Analyst -> Test Architect -> Reporting.
- politica de origen, rutas permitidas y rutas bloqueadas;
- Chromium real contra una aplicacion local determinista;
- screenshot y trace reales;
- deteccion de excepcion JavaScript;
- bloqueo de una solicitud hacia `example.com`;
- run completo Test Architect -> Browser Automation -> Reporting.
- rechazo de targets runtime internos, metadata y DNS que resuelve a IP privada;
- separacion entre rutas navegables y subrecursos del mismo origen;
- run combinado Repository -> Test Architect -> Browser -> Reporting;
- correlacion de evidencia GitHub + Browser sin afirmar causalidad no demostrada.
- deteccion de monorepo Next.js + FastAPI por directorio;
- comandos asociados a su working directory real;
- archivos de PR agrupados por componente;
- ruta candidata `/checkout` derivada de `src/app/checkout/page.tsx`.

Validacion adicional del frontend:

```text
npm audit
found 0 vulnerabilities

npm run build
Compiled successfully
```

Tambien se valido con Chromium:

- formulario QA Director sin overflow horizontal en desktop y movil;
- preview real con cuatro agentes para una mision combinada;
- ejecucion real de repositorio desde la UI hasta estado `completed`;
- diez eventos SSE observados y componente renderizado desde la salida real.

Tambien se realizo un smoke test real, sin token, contra `octocat/Hello-World`:

```text
repository=Hello-World branch=master files=1 captured=0 truncated=False
```

La aplicacion demo tambien se valido en el navegador integrado:

```text
/healthy -> title="Healthy checkout"; status="All systems operational."
/broken  -> console error="demo checkout initialization failed"
```

## Limitaciones conocidas

- Hay executors reales para Repository Analyst, Test Architect, Browser Automation y Reporting.
- La factory generica `api.app:create_app` sigue sin executors; para GitHub se debe usar
  `api.github_factory:create_github_app`.
- Todavia no existen endpoints de projects, targets, findings, artifacts o GitHub Checks.
- No hay autenticacion ni autorizacion HTTP implementadas.
- El frontend actual no tiene login, listado persistente de proyectos ni historial navegable.
- La UI habilita unicamente Repository y Browser Functional; las demas areas se muestran
  explicitamente como pendientes.
- Browser Automation es navigation-only: todavia no ejecuta clicks, formularios ni login.
- La redaccion textual cubre patrones comunes, pero las capturas visuales todavia no tienen un
  pipeline automatico de deteccion/redaccion de datos sensibles.
- Los traces Playwright tambien pueden contener datos sensibles; no deben usarse todavia con
  sesiones autenticadas ni datos reales.
- La correlacion combinada comparte contexto de mision, perfil y cambio, pero todavia no puede
  demostrar que un archivo especifico causa un fallo en una ruta.
- La deteccion multicomponente depende de manifests capturados y puede dejar archivos globales
  como `unmapped` cuando no pertenecen claramente a ningun componente.
- Las rutas candidatas solo cubren convenciones estaticas Next.js; no se inventan parametros
  para rutas dinamicas.
- Los artefactos usan filesystem local; aun no existe adapter S3 ni endpoint de descarga.
- Los runs activos viven como tareas del proceso; el checkpoint es durable, pero reanudar una
  ejecucion interrumpida tras reiniciar el servidor aun no esta implementado.
- La ruta separada `/events/stream` se eligio para no mezclar respuesta JSON y SSE en el mismo
  endpoint.

## Siguiente corte recomendado

La inteligencia multicomponente, el frontend mínimo de QA Director y la persistencia automática
en Neon ya están implementados. El siguiente corte recomendado es seguridad e historial:

1. Implementar autenticación HTTP mínima antes de cualquier despliegue público.
2. Agregar endpoints de listado de runs, findings y artefactos para el dashboard.
3. Implementar historial navegable en QA Director.
4. Integrar Accessibility con axe y correlación Browser + Accessibility.
5. Después incorporar Security básico y Performance smoke sin pruebas destructivas.

Trabajo complementario pendiente: endpoints de findings y artefactos, persistencia/reanudacion
de tareas tras reiniciar el proceso y almacenamiento externo de artefactos.

## Referencias principales

- `Swarm_AI_QA_PRD_v1.0.md`
- `docs/adr/ADR-011-orchestration-execution-kernel.md`
- `docs/adr/ADR-012-read-only-qa-product-boundary.md`
- `orchestrator/README.md`
- `schemas/README.md`
- `database/README.md`
- `api/README.md`
- `adapters/github/README.md`
- `demo_web/README.md`
- Documentacion oficial Playwright: `https://playwright.dev/python/docs/network`
- Tracing Playwright: `https://playwright.dev/python/docs/api/class-tracing`
