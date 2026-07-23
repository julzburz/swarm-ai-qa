# Continuidad del proyecto Swarm AI QA

Última actualización: 23 de julio de 2026, zona horaria America/La_Paz.

Este documento es el punto de traspaso para continuar el proyecto con otro agente. Antes de
hacer cambios, el siguiente agente debe leer este archivo, `README.md`, el PRD y los ADR
indicados al final.

## Resumen ejecutivo

Swarm AI QA es una plataforma de QA autónomo y estrictamente read-only. El usuario proporciona
un repositorio GitHub, una aplicación desplegada o ambos. QA Director realiza reconocimiento
acotado, diseña el plan y coordina un enjambre de especialistas reales. Los especialistas prueban,
intentan encontrar fallos y reúnen evidencia; nunca cambian el código del proyecto evaluado.

El MVP ya está desplegado y funcional:

- Frontend: https://swarm-ai-aq.vercel.app/
- Backend: https://swarm-ai-qa-backend-production.up.railway.app
- Health check: https://swarm-ai-qa-backend-production.up.railway.app/healthz
- Repositorio: https://github.com/julzburz/swarm-ai-qa
- Rama estable: `main`
- Versión del backend: `0.12.0`
- Persistencia activa: Neon PostgreSQL

Verificación en vivo realizada el 23 de julio de 2026:

```text
frontend_status=200
backend_status=ok
backend_version=0.12.0
storage=neon
```

El último commit funcional antes de actualizar este documento es:

```text
87d61de feat: add resilient deep QA execution
```

## Regla de producto no negociable

Los agentes son exclusivamente un equipo de QA:

- pueden inspeccionar repositorios mediante GitHub REST en modo read-only;
- pueden navegar y observar aplicaciones autorizadas;
- pueden ejecutar pruebas seguras y acotadas;
- pueden crear estrategias, matrices, casos, escenarios BDD, hallazgos e informes;
- pueden recomendar aprobar, condicionar o bloquear un release;
- no pueden editar, corregir, refactorizar, abrir PR, hacer commit ni desplegar el código evaluado;
- no deben inventar resultados, actividad, cobertura ni evidencia;
- producción permanece pasiva: navegación y solicitudes públicas `GET/HEAD`;
- acciones funcionales limitadas solo se permiten con opt-in en staging o sandbox.

Toda mejora futura debe preservar esta frontera.

## Cómo funciona actualmente

Flujo para repositorio y aplicación en producción:

```text
Usuario ingresa repo y/o URL
  -> reconocimiento GitHub read-only
  -> reconocimiento HTTP same-origin acotado
  -> QA Director crea preview y estima alcance
  -> usuario aprueba el plan
  -> scheduler ejecuta agentes reales según dependencias
  -> cada especialista produce evidencia y hallazgos
  -> Evidence & Reporting consolida aunque otro agente falle
  -> Release Manager emite recomendación en examen completo
  -> UI muestra actividad real y permite descargar HTML/Markdown
```

El plan ya no se basa solamente en lo escrito por el usuario. Antes del preview se inspeccionan
el repositorio y la URL de forma segura. La base del plan puede ser
`combined_reconnaissance`, y las rutas descubiertas se incorporan a la misión que se aprueba.

La detección del repositorio reconoce lenguajes, frameworks, runtimes, herramientas de test,
monorepos, componentes, comandos con su directorio de trabajo y rutas estáticas verificables de
Next.js. No se inventan valores para rutas dinámicas.

El reconocimiento runtime:

- hace solicitudes `GET` acotadas;
- sigue únicamente rutas same-origin autorizadas;
- prueba ubicaciones conocidas de OpenAPI;
- excluye rutas de contratos API de los journeys de página;
- limita el número de rutas según la profundidad elegida.

## Modos de profundidad

QA Director ofrece tres niveles:

| Modo | Uso | Presupuesto máximo | Paralelismo | Reconocimiento |
|---|---|---:|---:|---:|
| Trabajo rápido | Uno o dos encargos de QA | 300 s / 100 requests | 2 | Hasta 1 ruta |
| Examen coordinado | Varias áreas relevantes | 1200 s / 600 requests | 4 | Hasta 5 rutas |
| Examinación completa | Evaluación amplia y decisión de release | 2700 s / 1500 requests | 4 | Hasta 10 rutas |

La duración mostrada es una estimación basada en agentes, rutas, viewports y muestras. No se
añaden esperas artificiales. Una ejecución pequeña puede terminar rápido; una misión amplia crece
naturalmente con el trabajo real.

Performance usa 2, 3 o 5 muestras por ruta para trabajo rápido, examen coordinado y examinación
completa. Browser usa desktop en rápido; desktop y móvil en coordinado; desktop, tablet y móvil
en completo.

## Agentes reales conectados

| Agente | Función actual |
|---|---|
| QA Director | Reconocimiento, selección del equipo, presupuesto y plan |
| Repository Analyst | Perfil técnico, monorepo, componentes e impacto de cambios |
| Test Architect | Estrategia, matriz, casos y BDD/Gherkin |
| Browser Automation Engineer | Navegación funcional segura con Playwright |
| API Test Engineer | OpenAPI y pruebas públicas `GET/HEAD` sin mutaciones |
| Accessibility Specialist | axe-core 4.11.4 y cobertura WCAG automatizable |
| Security Test Engineer | Observación HTTP/TLS pasiva |
| Performance Test Engineer | Métricas de laboratorio single-user |
| Evidence & Reporting | Evidencia, trazabilidad, hallazgos e informe profesional |
| Release Manager | Recomendación ready/conditional/blocked en examen completo |

Existen perfiles YAML adicionales para la visión completa del producto, pero la UI solo debe
ofrecer especialistas con executor real. Nunca usar executors falsos para la demo.

## Orquestación y estados

El scheduler es asíncrono y soporta dependencias, paralelismo, retries, cancelación, checkpoints,
eventos y SSE.

La mejora principal de `0.12.0` es el reporte resiliente:

- las tareas normales usan dependencias `all_successful`;
- Reporting usa `all_terminal`;
- si un especialista falla, Reporting recibe ese fallo como contexto;
- el informe documenta cobertura incompleta y limitaciones;
- el run termina `completed_with_warnings` si existe informe válido con fallos parciales;
- el run solo termina `failed` si no puede completarse el informe necesario.

Esto evita el comportamiento anterior en el que un especialista fallido causaba que Evidence &
Reporting apareciera como `skipped`.

## Informe profesional

`QaRunReportV1` incluye:

- veredicto;
- fecha de generación;
- resumen ejecutivo;
- cobertura real;
- matriz y resultados de casos;
- trazabilidad hacia evidencia y findings;
- riesgos y limitaciones;
- recomendación de release cuando corresponde.

Veredictos posibles:

```text
approved
approved_with_observations
not_recommended
inconclusive
```

El reporter materializa versiones HTML y Markdown con hash SHA-256. La API cataloga y descarga
los artifacts mediante identificadores opacos. Los archivos se escriben fuera del repositorio
evaluado, bajo `SWARM_ARTIFACT_ROOT`.

## Validación completada

Suite automatizada:

```text
python -m unittest discover -s tests -v
Ran 91 tests
OK
```

También pasaron 7 subtests; se observaron 9 warnings no bloqueantes.

Frontend:

```text
npm run build
Compiled successfully
```

Se validó en producción un preview combinado con repositorio y frontend:

- base `combined_reconnaissance`;
- repo detectado como monorepo;
- runtime HTTP 200 y HTML;
- rutas `/` y `/control-plane/openapi.json` detectadas;
- misión enriquecida con las rutas reales;
- 8 agentes seleccionados;
- duración estimada aproximada de 7 minutos;
- ningún executor ausente.

También se lanzó una misión real de Accessibility a través del proxy de producción:

```text
run_id=5573c098-d403-4fac-bc1d-9e66f5ba6b7e
status=completed
accessibility=completed on first attempt
pages_scanned=1
finding_groups=1
reporting=completed
verdict=not_recommended
report_formats=HTML, Markdown
artifacts=3, all downloadable
```

El hallazgo fue de contraste de color. La UI mostró el run, la evidencia, la trazabilidad y los
tres downloads. El HTML se descargó con HTTP 200 y `Content-Type: text/html`.

## Estado de despliegue

Frontend:

- proveedor: Vercel;
- URL de producción: `https://swarm-ai-aq.vercel.app/`;
- el proxy server-side usa `SWARM_CONTROL_PLANE_URL`;
- si el backend está protegido, usa `SWARM_CONTROL_PLANE_API_KEY`;
- ningún secreto debe tener prefijo `NEXT_PUBLIC_`.

Backend:

- proveedor: Railway;
- URL de producción: `https://swarm-ai-qa-backend-production.up.railway.app`;
- imagen Docker multi-stage;
- instala `axe-core@4.11.4` en una etapa Node;
- copia `axe.min.js` a la imagen Python Playwright;
- configura `SWARM_AXE_SCRIPT_PATH`;
- health público en `/healthz`.

Base de datos:

- proveedor: Neon;
- `SWARM_STORAGE_BACKEND=auto` usa Neon cuando existe `DATABASE_URL`;
- SQLite es el fallback local;
- la cadena real de conexión no debe copiarse a este archivo ni al repositorio.

Variables relevantes:

```text
DATABASE_URL
SWARM_STORAGE_BACKEND
SWARM_API_KEY
GITHUB_TOKEN
SWARM_GITHUB_ALLOWED_PRIVATE_REPOSITORIES
SWARM_SQLITE_PATH
SWARM_ARTIFACT_ROOT
SWARM_AXE_SCRIPT_PATH
SWARM_CONTROL_PLANE_URL
SWARM_CONTROL_PLANE_API_KEY
```

Las claves solo deben existir en `.env` local o en los gestores de variables de Neon, Railway y
Vercel. `.env`, `.data/` y credenciales están excluidos de Git. Nunca registrar valores reales en
documentación, logs, commits o capturas.

## Preparación local

Backend en PowerShell:

```powershell
cd "D:\Proyectos\Swarm AI QA"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python -m uvicorn api.automation_factory:create_automation_app --factory --reload
```

Frontend en otra terminal:

```powershell
cd "D:\Proyectos\Swarm AI QA\frontend"
npm install
npm run dev
```

URLs locales:

- QA Director: `http://localhost:3000`
- Backend: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/healthz`

No hay servidores locales ni Docker ejecutándose como parte del traspaso.

## Limitaciones conocidas

- Los artifacts permanecen en filesystem local de Railway y pueden desaparecer en un redeploy o
  al mover la carga a otra réplica. Falta object storage compatible con S3.
- Los checkpoints son durables, pero una tarea activa no se reanuda automáticamente después de
  reiniciar el proceso.
- La autenticación usa una sola Bearer key; todavía no existen cuentas, sesiones, organizaciones
  ni roles.
- No existen aún proyectos persistentes, targets guardados, integración Jira ni GitHub Checks.
- Browser no automatiza login, pagos, logout, cambios de cuenta, `POST` ni acciones destructivas.
- API no cubre autenticación, GraphQL, parámetros obligatorios ni operaciones mutantes.
- axe no demuestra conformidad WCAG total; teclado, lector de pantalla, zoom y reflow quedan como
  pruebas manuales explícitas.
- Screenshots y traces no tienen todavía redacción visual automática; no usarlos con sesiones
  autenticadas o datos reales.
- Performance es laboratorio single-user; no sustituye RUM, carga, stress ni concurrencia y no
  mide INP representativo.
- La correlación repo-runtime comparte contexto, pero no puede afirmar causalidad exacta entre
  un archivo y un fallo sin un mapa verificable.
- Un run fallido antiguo puede seguir visible en el historial. Es anterior a `0.12.0` y no debe
  usarse para evaluar el reporte resiliente.

## Próximo paso recomendado

El siguiente agente debe priorizar una misión coordinada o completa real desde la UI de
producción. Objetivo: validar de extremo a extremo más de un dominio con la versión `0.12.0`,
confirmar crecimiento de rutas/viewports/muestras y revisar el informe combinado.

Secuencia sugerida:

1. Abrir `https://swarm-ai-aq.vercel.app/`.
2. Ingresar el repo público `https://github.com/julzburz/swarm-ai-qa`.
3. Ingresar el runtime `https://swarm-ai-aq.vercel.app/`.
4. Elegir examen coordinado; usar examinación completa solo si se acepta su mayor duración.
5. Confirmar que el preview diga `combined_reconnaissance`.
6. Revisar rutas, agentes, requests estimados y duración antes de aprobar.
7. Ejecutar y observar eventos, intentos, duración y estados reales.
8. Confirmar que Reporting termine aunque algún especialista falle.
9. Descargar HTML y Markdown y revisar veredicto, cobertura, casos, hallazgos y limitaciones.
10. Registrar el `run_id` y el resultado en este archivo.

Después de esa validación, la mejora técnica de mayor valor es externalizar artifacts a object
storage. No ampliar todavía a SaaS, usuarios o billing: no aporta tanto a la demo del hackathon
como asegurar evidencia durable e informe reproducible.

## Qué no debe rehacerse

- No volver a crear perfiles de agentes: ya existen.
- No sustituir actividad real por mocks.
- No añadir demoras artificiales para hacer parecer más profundo el análisis.
- No permitir que los agentes modifiquen el repo evaluado.
- No exponer `DATABASE_URL`, tokens o Bearer keys en el cliente.
- No desplegar la factory genérica `api.app:create_app`; producción usa
  `api.automation_factory:create_automation_app`.
- No asumir que un run viejo sin informe representa el comportamiento actual.

## Prompt breve para el siguiente agente

```text
Continúa Swarm AI QA desde CONTINUIDAD_PROYECTO.md. Primero verifica git status, el health de
Railway y el frontend de Vercel. No modifiques repositorios evaluados: el producto es QA
read-only. El siguiente objetivo es ejecutar y verificar una misión coordinada real
repo + producción con v0.12.0, revisar el informe HTML/Markdown y documentar el run_id.
Después, propone o implementa object storage para artifacts sin ampliar el SaaS.
```

## Referencias principales

- `Swarm_AI_QA_PRD_v1.0.md`
- `README.md`
- `api/README.md`
- `CONTINUIDAD_PROYECTO.md`
- `docs/adr/ADR-011-orchestration-execution-kernel.md`
- `docs/adr/ADR-012-read-only-qa-product-boundary.md`
- `orchestrator/README.md`
- `schemas/README.md`
- `database/README.md`
- `adapters/github/README.md`
- `demo_web/README.md`
