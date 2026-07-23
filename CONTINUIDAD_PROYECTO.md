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
- worker axe-core y executor real de Accessibility Specialist;
- correlacion Browser + Accessibility por URL autorizada;
- worker HTTP/TLS y executor real de Security Test Engineer pasivo;
- correlacion Browser + Security por URL autorizada, sin afirmar explotabilidad;
- worker Chromium y executor real de Performance Test Engineer single-user;
- correlacion Browser + Performance por URL autorizada, sin afirmar regresion;
- Test Design Studio con estrategia, matriz, casos y BDD/Gherkin;
- trazabilidad caso -> ejecución -> evidencia -> findings, sin simular resultados manuales;
- aplicacion web demo local y determinista;
- frontend Next.js de QA Director conectado al control plane;
- deteccion de monorepos y componentes con impacto de cambio por componente;
- seleccion automatica y persistencia durable en Neon con fallback SQLite;
- autenticacion Bearer opcional y proxy Next.js que conserva la clave en el servidor;
- historial navegable de runs reales desde QA Director;
- consulta filtrable de findings y descarga de artifacts con verificacion SHA-256;
- 80 pruebas automatizadas verdes.

El proyecto esta versionado en `https://github.com/julzburz/swarm-ai-qa`. La rama estable es
`main`; no copiar ni publicar `.env`, `.data/` ni credenciales.

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

## Actualizacion implementada: Accessibility Specialist real

La factory de automatizacion registra un especialista de accesibilidad respaldado por axe-core
4.11.4 y Playwright:

- navega unicamente rutas autorizadas mediante `GET/HEAD`;
- aplica reglas automatizables WCAG A/AA 2.0, 2.1 y 2.2;
- guarda resultados JSON redactados fuera del repositorio evaluado;
- convierte violaciones en findings con regla, impacto, selectores y evidencia;
- solicita verificacion de teclado/foco para findings high y critical;
- correlaciona findings axe con evidencia Browser de la misma URL;
- declara expresamente que axe no demuestra conformidad WCAG total.

## Archivos agregados o modificados

- `api/app.py`: factory de FastAPI, rutas, JSON y SSE.
- `api/controller.py`: ciclo de vida de tareas asincronas y preflight de executors.
- `api/config.py`: configuracion minima desde entorno.
- `api/schemas.py`: contratos HTTP del primer corte.
- `api/README.md`: instrucciones breves del modulo.
- `api/github_factory.py`: factory con los tres executors GitHub reales.
- `api/automation_factory.py`: factory compuesta GitHub + Browser + Accessibility.
- `adapters/github/`: cliente REST, modelos internos y limites read-only.
- `workers/browser/`: puerto, modelos y worker Playwright.
- `workers/accessibility/`: contratos y worker Playwright + axe-core.
- `executors/repository.py`: perfil tecnologico, contexto e impacto de PR.
- `executors/test_architect.py`: estrategia y cobertura basadas en evidencia.
- `executors/browser.py`: conversion de capturas en evidencia, journeys y findings.
- `executors/accessibility.py`: findings axe, cobertura y solicitudes de verificacion.
- `executors/reporting.py`: reporte final sin inventar findings.
- `executors/factory.py`: registro explicito del primer enjambre ejecutable.
- `demo_web/`: objetivo local determinista sano, roto y con solicitud externa.
- `tests/test_api.py`: seis pruebas del control plane.
- `tests/test_github_slice.py`: cliente HTTP y run GitHub completo con fixtures.
- `tests/test_browser_worker.py`: politica, Chromium real y run runtime completo.
- `tests/test_accessibility_agent.py`: axe real, executor y correlacion con Browser.
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

Este request es aceptado por `api.github_factory:create_github_app`. Para misiones runtime de
Browser, Accessibility, Security o Performance se usa
`api.automation_factory:create_automation_app`. API Test Engineer sigue pendiente.

## Verificacion realizada

Comando ejecutado:

```text
python -m unittest discover -s tests -v
```

Resultado al 23 de julio de 2026:

```text
Ran 76 tests
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
- escaneo axe real sobre paginas sanas y con barreras deliberadas;
- mision Accessibility aislada y correlacion Browser + Accessibility;
- Performance real con tres contextos Chromium aislados por ruta;
- metricas lab LCP, CLS, TTFB, carga, transferencia y recursos;
- mision Performance aislada y correlacion Browser + Performance;
- evidencia Performance descargable con verificacion SHA-256;
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

## Actualizacion implementada: Performance smoke seguro

Performance Test Engineer ya esta registrado en la factory de automatizacion:

- ejecuta tres muestras por ruta en contextos Chromium nuevos;
- usa solamente navegacion `GET/HEAD`, mismo origen, allowlist y presupuesto acotado;
- mide LCP, CLS, TTFB, DOMContentLoaded, load, FCP, transferencia y recursos;
- informa p75 de laboratorio, mediana, varianza y contexto de ejecucion;
- nunca ejecuta carga, stress o concurrencia;
- no mide INP porque no hay una interaccion representativa;
- no declara regresion sin baseline;
- guarda JSON redactado bajo `.data/artifacts/`, descargable por ID opaco y SHA-256 verificado.

Validacion Neon real:

```text
run_id=81d821ba-2d6e-4350-9d9c-9870a0963cb1
target=https://example.com/
samples=3/3
status=completed
restored_after_backend_restart=true
artifact_sha256_verified=true
```

## Actualizacion implementada: Test Design Studio

Test Architect genera una matriz compacta y trazable por ruta y dominio:

- caso, prioridad, riesgo, precondiciones, pasos y resultado esperado;
- escenario BDD/Gherkin en español;
- modo `automated` o `manual`;
- agente responsable y target exacto;
- resultado final enlazado a evidencia y findings;
- estados `passed`, `failed`, `observed`, `blocked`, `manual_required` y `not_executed`.

Los casos manuales nunca reciben executor ni evidencia automática. Gherkin es documentación QA
y no se escribe como código o archivos de prueba dentro del repositorio evaluado.

Validacion Neon real:

```text
run_id=baea006c-0bae-4784-a2ce-9c2473da5172
target=https://example.com/
test_cases=8
automated=4
manual_required=4
restored_after_backend_restart=true
frontend_proxy_verified=true
```

## Limitaciones conocidas

- Hay executors reales para Repository Analyst, Test Architect, Browser Automation,
  Accessibility, Security, Performance y Reporting.
- La factory generica `api.app:create_app` sigue sin executors; para GitHub se debe usar
  `api.github_factory:create_github_app`.
- Todavia no existen endpoints de projects, targets o GitHub Checks.
- La autenticacion actual usa una sola clave Bearer; aun no existen usuarios, sesiones ni roles.
- El frontend tiene historial de runs, pero aun no tiene listado persistente de proyectos.
- La UI habilita Repository, Browser Functional, Accessibility, Security y Performance.
- Browser Automation es navigation-only: todavia no ejecuta clicks, formularios ni login.
- Accessibility es automatizado con axe; teclado, lector de pantalla, zoom/reflow y estados
  interactivos permanecen como gaps manuales visibles.
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
- Los artefactos usan filesystem local; existe descarga verificada, pero aun no existe adapter
  S3.
- Performance es laboratorio single-user: no sustituye datos de usuarios reales, no mide INP
  y no prueba concurrencia.
- Los runs activos viven como tareas del proceso; el checkpoint es durable, pero reanudar una
  ejecucion interrumpida tras reiniciar el servidor aun no esta implementado.
- La ruta separada `/events/stream` se eligio para no mezclar respuesta JSON y SSE en el mismo
  endpoint.

## Siguiente corte recomendado

El siguiente corte recomendado es completar el especialista funcional sin ampliar el riesgo:

1. Agregar acciones Browser de lectura para clicks y formularios de prueba solo en staging.
2. Mantener produccion en navegacion pasiva salvo autorizacion y cuenta de prueba explicitas.
3. Incorporar API Test Engineer para contratos OpenAPI y operaciones `GET` seguras.
4. Preparar despliegue publico con `SWARM_API_KEY`; despues evaluar usuarios y roles.

Trabajo complementario pendiente: reanudacion de tareas tras reiniciar el proceso y
almacenamiento externo de artefactos.

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
