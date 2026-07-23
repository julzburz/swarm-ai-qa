**SWARM AI QA**

**Product Requirements Document (PRD)**

Plataforma autónoma multiagente de aseguramiento de calidad de software

Versión: 1.0  
Fecha: 20 de julio de 2026  
Ventana inicial: Hackathon Kiro AI powered by AWS (20-27 de julio de 2026)  
Estatus: Documento maestro para construcción mediante vibe coding

| **“No hicieron un chatbot. Construyeron un departamento completo de QA funcionando de forma autónoma dentro de una aplicación.”** |
|-----------------------------------------------------------------------------------------------------------------------------------|

# 0. Control del documento

| **Campo**           | **Valor**                                                                                            |
|---------------------|------------------------------------------------------------------------------------------------------|
| Producto            | Swarm AI QA                                                                                          |
| Tipo                | PRD + Technical Design + Agent Specification + AI Context Pack                                       |
| Versión             | 1.0                                                                                                  |
| Propietario         | Fundador / Product Owner                                                                             |
| Audiencia           | Producto, ingeniería, diseño, seguridad, QA, DevOps, inversores y agentes de vibe coding             |
| Fecha de creación   | 20 de julio de 2026                                                                                  |
| Entrega inicial     | 27 de julio de 2026                                                                                  |
| Horizonte de diseño | Startup escalable; la entrega del hackathon es la primera versión pública, no el límite del producto |
| Estado              | Aprobado como baseline inicial; cambios relevantes requieren Architecture Decision Record (ADR)      |

# 1. Resumen ejecutivo

Swarm AI QA es una plataforma SaaS de validación autónoma de software. Organiza agentes de inteligencia artificial como un departamento real de Quality Engineering: un QA Director planifica, especialistas ejecutan análisis por dominio, workers operan herramientas, y un Release Manager determina si un cambio puede avanzar hacia producción.

La plataforma analiza tanto artefactos estáticos —repositorios, pull requests, archivos, contenedores e infraestructura— como sistemas en ejecución —URLs públicas, staging, producción autorizada, APIs y entornos privados—. Su propósito es ejecutar trabajo real de QA, intentar descubrir fallos, construir evidencia reproducible, correlacionar hallazgos y emitir una decisión de release explicable sin modificar el código evaluado.

| **Tesis del producto —** El valor no está en “usar muchos agentes”, sino en asignar responsabilidades, capacidades, herramientas, permisos, memoria y criterios de calidad diferentes a cada rol, coordinados bajo una política común. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 2. Visión, misión y posicionamiento

## 2.1 Visión

Convertirse en la capa autónoma de confianza para cada cambio de software: desde el primer commit hasta el comportamiento real en producción.

## 2.2 Misión

Dar a desarrolladores y organizaciones un departamento de QA siempre disponible, reproducible, explicable y adaptable, sin obligarlos a construir su propia infraestructura de automatización.

## 2.3 Posicionamiento

Swarm AI QA no se posiciona como chatbot, generador de pruebas ni scanner aislado. Se posiciona como una organización autónoma de Quality Engineering capaz de observar, decidir, ejecutar y aprender.

## 2.4 Mensajes principales

- “Tu departamento autónomo de QA.”

- “Del repositorio al runtime: evidencia antes de aprobar.”

- “No demostramos que tu aplicación funciona; buscamos cómo puede fallar.”

- “Cada hallazgo es reproducible, trazable y respaldado por evidencia.”

# 3. Problema y oportunidad

## 3.1 Problemas actuales

- La calidad se fragmenta entre unit tests, E2E, seguridad, accesibilidad, rendimiento, observabilidad y QA manual.

- Los equipos pequeños no pueden contratar especialistas para todas las disciplinas.

- Las herramientas tradicionales producen datos aislados, pero no una decisión contextualizada de release.

- Los generadores de tests basados en LLM suelen desconocer el impacto real de un cambio y pueden producir pruebas superficiales.

- Los análisis de repositorio no garantizan que la aplicación desplegada funcione bajo condiciones reales.

- La documentación y las reglas de las herramientas cambian; prompts estáticos envejecen rápidamente.

- La automatización tradicional exige configuración y mantenimiento que muchos equipos no pueden sostener.

## 3.2 Oportunidad

Un sistema multiagente puede separar contextos, ejecutar herramientas especializadas en paralelo, contrastar evidencias, repetir pruebas y sintetizar una decisión. La arquitectura se justifica porque QA ya es una función organizacional dividida por especialidad.

# 4. Objetivos y no objetivos

## 4.1 Objetivos del producto

1.  Analizar cambios de código, repositorios completos y aplicaciones desplegadas.

2.  Descubrir automáticamente superficies de riesgo y construir un plan de pruebas.

3.  Ejecutar pruebas funcionales, E2E, API, seguridad, rendimiento, accesibilidad, regresión y resiliencia.

4.  Correlacionar hallazgos entre agentes y elevar o reducir confianza según evidencia cruzada.

5.  Entregar resultados de QA útiles: reportes, findings, métricas, evidencia y pasos de reproducción.

6.  Emitir un Release Confidence Score acompañado por una recomendación explicable.

7.  Mantener herramientas y conocimiento actualizados mediante registros versionados y fuentes oficiales.

8.  Permitir operación SaaS, self-hosted y enterprise privada sin cambiar el modelo conceptual.

## 4.2 No objetivos iniciales

- No prometer compatibilidad perfecta con todos los lenguajes desde el primer release.

- No ejecutar pruebas destructivas sobre producción sin autorización explícita y límites estrictos.

- No generar, editar, aplicar ni proponer código, tests, fixes, patches, commits, branches o pull requests.

- No actuar como agente de desarrollo. Swarm observa, prueba, intenta romper dentro del alcance autorizado y reporta resultados; nunca reescribe el producto evaluado.

- No sustituir auditorías legales, regulatorias o de seguridad certificadas.

- No garantizar ausencia total de defectos; el sistema mide y comunica riesgo residual.

# 5. Usuarios, segmentos y jobs-to-be-done

| **Segmento**                | **Necesidad principal**                                  | **Resultado esperado**                                    |
|-----------------------------|----------------------------------------------------------|-----------------------------------------------------------|
| Desarrollador independiente | Validar cambios sin mantener un equipo completo de QA    | Feedback rápido, evidencia y riesgos priorizados          |
| Startup                     | Liberar rápido sin equipo completo de QA                 | Cobertura multidisciplinaria con costos previsibles       |
| Equipo de producto          | Entender impacto funcional de cambios                    | Evidencia por flujo y decisión de release                 |
| QA / SDET                   | Escalar su capacidad y reducir trabajo repetitivo        | Planes de prueba, ejecución paralela y reportes trazables |
| Empresa mediana             | Estandarizar criterios entre equipos                     | Policies, dashboards, integraciones CI/CD y auditoría     |
| Enterprise                  | Gobernanza, privacidad y despliegue interno              | SSO, RBAC, data residency, VPC/self-hosted y controles    |
| Open source                 | Detectar regresiones y mejorar contribuciones            | Análisis accesible para PRs comunitarios                  |

# 6. Alcance funcional

## 6.1 Fuentes de entrada diseñadas

| **Categoría**    | **Entradas previstas**                                                 | **Prioridad**            |
|------------------|------------------------------------------------------------------------|--------------------------|
| Código           | GitHub, GitLab, Bitbucket, ZIP, carpeta local, monorepo                | GitHub: P0; resto: P1-P2 |
| Runtime web      | URL pública, staging, producción autorizada, localhost mediante runner | URL pública/staging: P0  |
| Contenedores     | Dockerfile, imagen OCI, Docker Compose                                 | P1                       |
| Infraestructura  | Kubernetes, Terraform, CloudFormation, AWS                             | P2                       |
| APIs             | OpenAPI, GraphQL, gRPC, WebSocket                                      | OpenAPI/REST: P1         |
| Móvil/escritorio | React Native, Flutter, Android, iOS, Electron                          | P3                       |
| CI/CD            | GitHub Actions, GitLab CI, Jenkins, CircleCI                           | GitHub Actions: P1       |
| Observabilidad   | CloudWatch, OpenTelemetry, Sentry, Datadog, Grafana                    | CloudWatch/Sentry: P2    |

## 6.2 Alcance demostrable del 27 de julio de 2026

- Conectar un repositorio GitHub y seleccionar rama o pull request.

- Analizar diff, estructura, dependencias y riesgos.

- Ejecutar al menos una verificación automatizada real y conservar su evidencia.

- Introducir una URL desplegada y descubrir flujos básicos mediante Playwright.

- Ejecutar auditorías funcionales, seguridad web básica, rendimiento y accesibilidad.

- Mostrar actividad de agentes en tiempo real.

- Correlacionar al menos un hallazgo entre dos agentes.

- Entregar reporte final y Release Confidence Score.

# 7. Modelo operativo multiagente

## 7.1 Principios

- Especialización real: cada agente posee objetivo, contexto, métricas y capacidades distintas.

- Control centralizado: el QA Director conserva el estado del trabajo y resuelve dependencias.

- Ejecución distribuida: tareas independientes se ejecutan en paralelo.

- Evidencia primero: ninguna afirmación crítica se acepta sin salida de herramienta o artefacto reproducible.

- Mínimo privilegio: los agentes solo acceden a capacidades autorizadas.

- Human-in-the-loop configurable: autonomía creciente sin perder control empresarial.

- Context isolation: los especialistas reciben solo el contexto necesario para reducir errores y costo.

## 7.2 Jerarquía organizacional

Usuario / CI / Webhook  
\|  
v  
QA Director (orquestador, planner y supervisor)  
\|  
+--\> Test Architect  
+--\> Repository Analyst  
+--\> Browser Automation Engineer  
+--\> Security Test Engineer  
+--\> Performance Test Engineer  
+--\> Accessibility Specialist  
+--\> Regression Analyst  
+--\> Chaos & Resilience Engineer  
+--\> Release Manager  
+--\> Evidence & Reporting Analyst  
\|  
v  
Workers / Tool Adapters / MCP Servers  
\|  
v  
GitHub, Playwright, Semgrep, Gitleaks, k6, axe, Lighthouse, Docker, HTTP, AWS

## 7.3 Catálogo de agentes

| **Agente**                   | **Rol real equivalente**                | **Responsabilidad**                                                                                       | **Personalidad UX**                                   |
|------------------------------|-----------------------------------------|-----------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| QA Director                  | Head of QA / QA Lead                    | Interpretar objetivo, planificar, delegar, priorizar riesgo, resolver conflictos y mantener estado global | Serio, breve, orientado a evidencia                   |
| Test Architect               | Test Architect / SDET Lead              | Diseñar estrategia, pirámide de pruebas, criterios de aceptación y cobertura necesaria                    | Metódico y estratégico                                |
| Repository Analyst           | Code Quality Analyst                    | Indexar repo, diff, dependencias, ownership, lenguaje y superficies afectadas                             | Curioso y preciso                                     |
| Browser Automation Engineer  | Automation QA Engineer                  | Descubrir y ejecutar flujos UI con Playwright; capturar trazas, video y screenshots                       | Pragmático y persistente                              |
| API Test Engineer            | API QA Engineer                         | Derivar pruebas desde OpenAPI/tráfico y validar contratos, errores y edge cases                           | Obsesionado con contratos                             |
| Security Test Engineer       | Application Security Engineer           | Orquestar SAST, secrets, dependency, headers y pruebas seguras de abuso                                   | Paranoico por diseño                                  |
| Performance Test Engineer    | Performance Engineer                    | Diseñar smoke/load/stress; comparar SLOs y regresiones                                                    | Obsesionado con milisegundos                          |
| Accessibility Specialist     | Accessibility QA Specialist             | Auditar WCAG, teclado, semántica y experiencias asistivas                                                 | Empático y defensor del usuario                       |
| Regression Analyst           | Regression QA Analyst                   | Comparar baseline vs cambio; detectar desviaciones funcionales y no funcionales                           | Escéptico y comparativo                               |
| Chaos & Resilience Engineer  | Chaos Engineer / SRE                    | Probar fallos controlados, reintentos, timeouts, doble envío y degradación                                | Juguetón; disfruta encontrar formas seguras de romper |
| Release Manager              | Release Manager                         | Aplicar políticas, calcular confianza y recomendar Ready/Review/Blocked sin operar el pipeline             | Conservador y ejecutivo                               |
| Evidence & Reporting Analyst | QA Reporting Analyst                    | Normalizar evidencias, deduplicar hallazgos y producir informes accionables                               | Ordenado y transparente                               |
| Tool Intelligence Agent      | Developer Experience / Tooling Engineer | Vigilar versiones, documentación y salud de adaptadores                                                   | Actualizador y preventivo                             |
| Knowledge Curator            | Technical Librarian                     | Ingerir y versionar fuentes oficiales para RAG                                                            | Riguroso con procedencia                              |

### 7.3.1 Perfiles implementables

Los contratos operativos de los agentes se mantienen en [`agents/`](agents/README.md). Cada perfil define misión, estado de entrega, entradas, salidas, capacidades permitidas y prohibidas, política de decisión, colaboración, evidencia y métricas de éxito. Los mensajes del camino crítico están implementados como modelos Pydantic versionados en [`schemas/`](schemas/README.md). `Project Intelligence` forma parte del Repository Analyst durante el hackathon e incluye detección de lenguajes, frameworks, runtimes, gestores de paquetes, herramientas de testing y componentes de monorepos.

## 7.4 Comunicación entre agentes

La comunicación directa se permite solo cuando reduce incertidumbre o valida evidencia. El QA Director conserva la autoridad de planificación; los agentes no generan conversaciones libres ilimitadas.

| **Patrón**        | **Ejemplo**                                                                                 | **Valor**                                     |
|-------------------|---------------------------------------------------------------------------------------------|-----------------------------------------------|
| Consulta dirigida | Security pregunta a Browser si una cookie observada es Secure/HttpOnly                      | Verificación dinámica de un hallazgo estático |
| Comparación       | Performance pregunta a Regression por el baseline del endpoint                              | Determinar si existe degradación              |
| Escalamiento      | Accessibility solicita al Browser una navegación completa por teclado                       | Reproducir el problema                        |
| Dependencia       | Test Architect espera el mapa de impacto del Repository Analyst                             | Evitar tests irrelevantes                     |
| Debate controlado | Security y Release Manager discrepan sobre severidad; Director solicita evidencia adicional | Resolver conflicto sin votación arbitraria    |

## 7.5 Protocolo de mensajes

{  
"message_id": "uuid",  
"run_id": "uuid",  
"from_agent": "security_test_engineer",  
"to_agent": "browser_automation_engineer",  
"intent": "VERIFY_FINDING",  
"priority": "HIGH",  
"context_refs": \["artifact://scan/123", "url://target/login"\],  
"question": "Verifica atributos de la cookie session_id tras login.",  
"expected_output_schema": "CookieVerificationV1",  
"deadline_ms": 60000,  
"permissions": \["browser.read", "network.observe"\]  
}

# 8. Agent Constitution

La constitución es obligatoria para todos los agentes, prompts, workers y herramientas. Las políticas no dependen del proveedor LLM.

9.  No inventar resultados, ejecuciones, archivos, métricas ni cobertura.

10. Toda afirmación de severidad alta o crítica debe apuntar a evidencia reproducible.

11. Distinguir observación, inferencia y recomendación.

12. No ejecutar acciones destructivas o irreversibles fuera de un sandbox autorizado.

13. No atacar dominios o sistemas sin autorización verificable.

14. No exfiltrar secretos; redactarlos en logs y reportes.

15. Respetar scopes de credenciales y políticas de mínimo privilegio.

16. Detenerse ante incertidumbre material o señales de impacto no controlado.

17. No aprobar un release si faltan pruebas obligatorias definidas por policy.

18. Todo hallazgo debe incluir pasos de reproducción, evidencia, impacto, confianza y recomendación.

19. Los agentes deben utilizar esquemas estructurados y validar sus salidas.

20. Los errores de herramienta no se reinterpretan como resultados negativos o positivos.

21. Cada decisión debe quedar registrada en un audit trail.

22. El sistema debe preferir fuentes oficiales y versionadas para conocimiento técnico.

23. La personalidad visual nunca puede reducir profesionalismo ni ocultar riesgo.

24. Ningún agente puede generar, editar, aplicar o proponer cambios de código, tests, configuración, commits, branches o pull requests.

25. Los repositorios son fuentes de lectura. Los workers pueden crear archivos técnicos efímeros internos para operar herramientas, pero esos archivos no se presentan como código entregable ni se escriben en el repositorio del usuario.

26. El Release Manager emite una recomendación; nunca aprueba pipelines, despliega, fusiona o modifica el estado del código del usuario.

# 9. Modelo de operación y permisos

| **Modo**                   | **Capacidad**                                                    | **Política**                                                |
|----------------------------|------------------------------------------------------------------|-------------------------------------------------------------|
| Inspect                    | Lee repositorios, diffs, artefactos y superficies observables    | Solo lectura                                               |
| Execute in sandbox         | Ejecuta suites y scanners sobre una copia efímera                | Aislamiento y límites obligatorios                         |
| Test authorized runtime    | Ejecuta flujos funcionales y auditorías sobre URL autorizada     | Allowlist, presupuesto y acciones seguras                  |
| Safe adversarial QA        | Intenta romper flujos con inputs y fallos controlados            | Solo sandbox/staging o permiso explícito; nunca destructivo |
| Recommend release decision | Emite Ready, Conditional, Manual Review o Blocked con evidencia  | Recomendación informativa; no cambia pipelines ni código   |

| **Decisión —** Swarm AI QA es permanentemente read-only respecto al código del usuario. La autonomía se limita a seleccionar y ejecutar pruebas autorizadas y a entregar evidencia; nunca se extiende a desarrollo o modificación del producto. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 10. Arquitectura de plataforma

## 10.1 Vista lógica

\[Next.js Web App\]  
\| HTTPS / WebSocket / SSE  
\[FastAPI Control Plane\]  
\|  
+-- Identity / Organizations / Billing / Projects  
+-- Run API / Webhooks / Policy Engine  
+-- LangGraph Orchestrator  
\| +-- QA Director  
\| +-- Specialist Nodes  
\| +-- Human approval interrupts  
\|  
+-- Capability Manager  
+-- Tool Registry + MCP Gateway  
+-- LLM Provider Gateway  
+-- Knowledge Hub / RAG  
+-- Evidence Store  
+-- Event Bus / Job Queue  
\|  
\[Execution Plane - isolated workers\]  
+-- Browser Workers  
+-- Code Scan Workers  
+-- Performance Workers  
+-- Container / Chaos Workers  
\|  
\[Data\]  
+-- Neon PostgreSQL + pgvector  
+-- Redis-compatible cache/queue  
+-- S3 artifacts  
+-- CloudWatch / OpenTelemetry

## 10.2 Stack recomendado

| **Capa**        | **Tecnología**                              | **Razón**                                                           | **Alternativa**                                          |
|-----------------|---------------------------------------------|---------------------------------------------------------------------|----------------------------------------------------------|
| Frontend        | Next.js + TypeScript + Tailwind + shadcn/ui | Ecosistema rápido, dashboard y streaming                            | Remix / React SPA                                        |
| Backend         | FastAPI + Python                            | Excelente para agentes, tooling y APIs async                        | NestJS                                                   |
| Orquestación    | LangGraph                                   | Estado explícito, nodos, reanudación, paralelismo e interrupts      | Orquestación propia sobre Temporal                       |
| LLM gateway     | Adaptador propio con Google GenAI SDK       | Desacopla agentes del proveedor                                     | LiteLLM como implementación interna                      |
| Modelo primario | Gemini 3.1 Flash-Lite                       | Baja latencia, multimodal, function calling y outputs estructurados | Gemini 2.5 Flash-Lite / modelo premium para escalamiento |
| Base de datos   | Neon PostgreSQL                             | Serverless Postgres; ambientes/branches; buen fit inicial           | Amazon Aurora PostgreSQL                                 |
| Vectores        | pgvector en Postgres                        | Reduce sistemas operados al inicio                                  | OpenSearch / Qdrant                                      |
| Cache/colas     | Redis compatible (Upstash inicialmente)     | Cache, locks, rate limits, event fan-out y jobs cortos              | Amazon ElastiCache / SQS                                 |
| Artefactos      | Amazon S3                                   | Screenshots, videos, traces, logs y reportes                        | MinIO self-hosted                                        |
| Contenedores    | Docker                                      | Reproducibilidad y aislamiento                                      | Firecracker sandbox futuro                               |
| Runtime AWS     | ECS Fargate                                 | Workers aislados y escalables sin gestionar nodos                   | EKS / Lambda para tareas cortas                          |
| Observabilidad  | OpenTelemetry + CloudWatch                  | Trazas, logs, métricas y alineación AWS                             | Grafana Cloud                                            |
| Auth            | Clerk/Auth.js para inicio; OIDC/SAML futuro | Velocidad inicial                                                   | Amazon Cognito                                           |
| Billing         | Stripe                                      | Suscripciones y metered billing                                     | Paddle                                                   |

## 10.3 Decisión LangGraph

Se recomienda LangGraph porque Swarm necesita procesos largos, estado persistente, fan-out/fan-in, retries, checkpoints, interrupciones para aprobación humana y visualización de nodos. No se utilizará un framework de “roles conversando” como núcleo; los agentes serán nodos y subgrafos con contratos claros.

El vertical slice implementa primero un [kernel de ejecución desacoplado](orchestrator/README.md) con los mismos contratos, eventos y puertos que utilizarán los nodos. Esta decisión complementaria está documentada en [ADR-011](docs/adr/ADR-011-orchestration-execution-kernel.md) y no reemplaza la integración LangGraph prevista por ADR-002.

## 10.4 Neon y migración futura

Neon es adecuado para la fase inicial y puede alojar datos relacionales y embeddings mediante pgvector. La capa de acceso se implementará con SQLAlchemy y migraciones Alembic para mantener portabilidad hacia Aurora PostgreSQL si los requisitos de enterprise, red privada o residencia de datos lo exigen.

La implementación inicial se documenta en [`database/`](database/README.md): conexión pooled para la aplicación, conexión directa para migraciones, modelos SQLAlchemy, Alembic, `NeonRunStore` y SQLite como fallback local de tests. Los artefactos pesados permanecen fuera de PostgreSQL y se referencian desde la tabla `artifacts`.

# 11. LLM Provider Gateway y resiliencia

## 11.1 Corrección del modelo

El nombre validado en la documentación oficial actual es Gemini 3.1 Flash-Lite (\`gemini-3.1-flash-lite\`). El PRD no debe fijar “Gemini 3.5 Flash-Lite” porque no corresponde al identificador oficial consultado al 20 de julio de 2026.

## 11.2 Política de modelos

| **Clase de tarea**                 | **Modelo por defecto**                      | **Escalamiento**                                      |
|------------------------------------|---------------------------------------------|-------------------------------------------------------|
| Clasificación, routing, extracción | Gemini 3.1 Flash-Lite                       | No necesario salvo baja confianza                     |
| Planificación moderada             | Gemini 3.1 Flash-Lite con thinking limitado | Modelo de mayor capacidad si el plan falla validación |
| Síntesis de reporte                | Gemini 3.1 Flash-Lite                       | Modelo premium para reportes enterprise opcionales    |
| Visión de UI                       | Gemini multimodal vía gateway               | Fallback a OCR/DOM, no alucinación visual             |
| Análisis complejo de código         | Modelo configurable por tenant              | Toda conclusión requiere evidencia reproducible       |

## 11.3 Cadena de claves

El gateway puede mantener múltiples credenciales para disponibilidad operativa, rotación y separación por entorno. Sin embargo, las cuotas de Gemini se aplican por proyecto y no se deben rotar claves para evadir límites. La resiliencia debe implementarse con backoff, circuit breaker, control de concurrencia, cache semántica, presupuestos de tokens y fallback legítimo a otro proyecto autorizado o proveedor.

Provider selection policy:  
1. Select tenant + task policy  
2. Check model health and budget  
3. Acquire rate-limit token  
4. Execute with idempotency key  
5. On 429: exponential backoff + jitter  
6. On repeated failure: open circuit  
7. Route to approved fallback model/provider  
8. Validate structured output  
9. Record latency, tokens, cost and error class

## 11.4 Configuración de credenciales

- No almacenar API keys en base de datos en texto plano.

- Usar AWS Secrets Manager para producción y variables seguras para desarrollo.

- Separar claves por ambiente y organización cuando aplique.

- Rotación programada y revocación inmediata.

- Nunca exponer credenciales a prompts, agentes o frontend.

- Rate limiter por proveedor, proyecto, modelo, tenant y run.

# 12. Capability Layer

Los agentes solicitan capacidades, no herramientas concretas. Esto evita acoplamiento y permite reemplazar Semgrep por otra implementación sin modificar el Security Test Engineer.

## 12.1 Contrato de capacidad

capability_id: static_security_scan  
version: 1.0.0  
input_schema: StaticScanInputV1  
output_schema: StaticScanEvidenceV1  
required_permissions:  
- repository.read  
risk_class: LOW  
execution_environment: sandbox  
providers:  
- semgrep_adapter  
- codeql_adapter  
selection_policy:  
prefer: semgrep_adapter  
fallback: codeql_adapter  
quality_gates:  
- output_schema_valid  
- tool_exit_code_captured  
- findings_have_locations

## 12.2 Capacidades iniciales

| **Dominio**   | **Capacidades**                                                                               |
|---------------|-----------------------------------------------------------------------------------------------|
| Repositorio   | clone_repository, inspect_diff, detect_languages, build_dependency_map, search_symbols        |
| Testing       | discover_existing_tests, run_tests, measure_coverage, create_test_data, validate_contract     |
| Browser       | discover_routes, navigate_flow, fill_form, capture_trace, capture_screenshot, observe_network |
| Security      | static_security_scan, secret_scan, dependency_scan, header_audit, safe_input_fuzz             |
| Performance   | run_smoke_test, run_load_test, collect_web_vitals, compare_baseline                           |
| Accessibility | run_axe_audit, keyboard_navigation_check, semantic_review                                     |
| Chaos         | simulate_timeout, duplicate_submit, network_offline, service_fault_in_sandbox                 |
| Reporting     | publish_report, publish_github_check, export_evidence                                       |
| Knowledge     | retrieve_official_docs, resolve_tool_version, retrieve_policy                                 |

# 13. Tool Registry y MCP

## 13.1 Experiencia del usuario

El usuario no debe programar MCPs para usar Swarm. La plataforma incluye conectores y servidores MCP administrados. El usuario solo conecta una cuenta, instala una GitHub App o proporciona credenciales con scopes mínimos. Para casos internos, podrá registrar un MCP privado desde un catálogo enterprise.

## 13.2 Ejemplo de uso

Usuario conecta GitHub App  
\|  
Swarm registra connector github.default  
\|  
Repository Analyst solicita capability: inspect_pull_request  
\|  
Capability Manager selecciona GitHub MCP  
\|  
Worker llama tools: get_pr, get_diff, get_file, create_check_run  
\|  
Resultado estructurado vuelve al agente  
\|  
El agente razona; nunca ve el token de GitHub

## 13.3 Herramientas de referencia

| **Capacidad**    | **Herramienta inicial**               | **Uso**                                             |
|------------------|---------------------------------------|-----------------------------------------------------|
| Git hosting      | GitHub App + GitHub API/MCP           | Lectura de repos/PRs y publicación opcional de Checks |
| Browser E2E      | Playwright                            | Navegación, traces, screenshots, video y assertions |
| SAST             | Semgrep                               | Reglas estáticas multilenguaje                      |
| Secrets          | Gitleaks                              | Detección de secretos en historial y workspace      |
| Dependencies     | Trivy / OSV-Scanner                   | Vulnerabilidades de paquetes e imágenes             |
| Performance      | Grafana k6                            | Smoke, load, stress, spike y API testing            |
| Web performance  | Lighthouse / Chrome DevTools Protocol | Web Vitals y auditorías frontend                    |
| Accessibility    | axe-core + Playwright                 | Auditoría automatizada WCAG                         |
| Unit/integration | Framework nativo detectado            | pytest, Vitest/Jest, JUnit, Go test, etc.           |
| Containers       | Docker API                            | Build y ejecución aislada                           |
| Cloud            | AWS SDK / MCP autorizado              | CloudWatch, ECS, S3 y recursos permitidos           |

## 13.4 Registro de herramientas

tool_id: playwright  
adapter_version: 1.0.0  
upstream_version: pinned  
capabilities: \[discover_routes, navigate_flow, capture_trace\]  
source_of_truth: official_docs  
last_verified_at: ISO-8601  
health_status: healthy  
compatibility_matrix:  
node: \[supported_versions\]  
security_profile:  
network: restricted  
filesystem: ephemeral  
secrets: injected_at_runtime  
smoke_test: tool-tests/playwright-smoke.yaml

# 14. Tool Intelligence y conocimiento actualizado

Swarm no permitirá que los agentes dependan de memoria estática del LLM para comandos, APIs o estándares. El sistema mantendrá un Knowledge Hub versionado y un proceso de Tool Intelligence.

## 14.1 Fuentes de verdad

- Documentación oficial del proveedor de cada herramienta.

- Releases y changelogs oficiales.

- OWASP, CWE y fuentes normativas autorizadas.

- Guías oficiales de AWS y plataformas integradas.

- Repositorios oficiales y esquemas de APIs.

- Políticas internas de cada organización.

## 14.2 Pipeline de actualización

24. Detectar nueva versión, cambio de documentación o deprecation.

25. Crear snapshot versionado de contenido y metadata.

26. Ejecutar parser y chunking con procedencia.

27. Actualizar embeddings sin eliminar versiones anteriores.

28. Ejecutar compatibility tests del adaptador.

29. Abrir propuesta de actualización del Tool Registry.

30. Requerir aprobación humana para cambios breaking en producción.

31. Desplegar canary, observar errores y permitir rollback.

## 14.3 Protección contra documentación maliciosa

- Tratar contenido recuperado como datos, nunca como instrucciones privilegiadas.

- Eliminar scripts y contenido activo.

- Aplicar allowlist de dominios y firmas/hash de snapshots.

- Conservar procedencia, fecha, versión y licencia.

- Bloquear prompt injection contenida en repositorios o documentación.

- Separar system policies de RAG context.

# 15. Memoria, cache y estado

| **Capa**                      | **Tecnología**                    | **Contenido**                                                  | **TTL**                      |
|-------------------------------|-----------------------------------|----------------------------------------------------------------|------------------------------|
| L0 - Run state                | LangGraph checkpoint + PostgreSQL | Estado del grafo, tareas y approvals                           | Duración del run + retención |
| L1 - Hot cache                | Redis compatible                  | Resultados idénticos, locks, tokens, sesiones y eventos        | Segundos a horas             |
| L2 - Project memory           | PostgreSQL                        | Baselines, historial, policies, findings y relaciones          | Persistente                  |
| L3 - Vector knowledge         | pgvector                          | Docs, código indexado, embeddings de evidencias                | Versionado                   |
| L4 - Artifact store           | S3                                | Video, screenshots, traces, logs, reportes y bundles           | Policy-based                 |
| L5 - Organizational knowledge | Postgres/pgvector                 | Aceptaciones de riesgo, falsos positivos y estándares internos | Persistente y auditable      |

## 15.1 Cache semántica

Puede reutilizar resultados solo cuando coincidan commit SHA, tool version, configuration hash, environment fingerprint y policy version. No se reutilizarán resultados de seguridad o release gates únicamente por similitud textual.

# 16. Flujos principales

## 16.1 Flujo Repository / Pull Request

32. Usuario instala GitHub App y selecciona repositorio/PR.

33. Webhook o acción manual crea un QA Run.

34. Repository Analyst obtiene metadata, diff y archivos relevantes.

35. Test Architect clasifica riesgo y genera el plan.

36. QA Director ejecuta especialistas en paralelo según riesgo.

37. Workers corren herramientas en workspace efímero.

38. Agentes correlacionan resultados y solicitan verificaciones cruzadas.

39. Release Manager aplica policy y calcula confianza.

40. Report Analyst publica dashboard y GitHub Check.

41. Swarm publica o exporta exclusivamente el reporte y sus evidencias; nunca crea branches, commits, tests, fixes o pull requests.

## 16.2 Flujo Live Application

42. Usuario registra URL, ambiente, credenciales de prueba y límites.

43. Swarm verifica autorización y dominio.

44. Browser Agent descubre rutas y flujos; el usuario puede confirmar critical journeys.

45. Se ejecutan pruebas funcionales y de accesibilidad.

46. Performance Agent ejecuta smoke por defecto; cargas mayores requieren aprobación.

47. Security Agent realiza auditorías no destructivas.

48. Chaos Agent aplica comportamientos de usuario y fallos seguros permitidos.

49. Se almacenan trazas y evidencia.

50. Release Manager emite score y riesgos residuales.

## 16.3 Flujo de colaboración

Security detecta cookie sin SameSite  
-\> solicita verificación al Browser Agent  
Browser reproduce login y captura headers  
-\> confirma evidencia  
Regression compara con ejecución anterior  
-\> identifica que el defecto apareció en el último deploy  
Release Manager aplica policy  
-\> recomienda bloquear el release y describe el riesgo que el equipo debe resolver  
Report Analyst crea pasos reproducibles y evidencia enlazada

# 17. Requisitos funcionales

| **ID** | **Área**                   | **Requisito**                                                         | **Prioridad** |
|--------|----------------------------|-----------------------------------------------------------------------|---------------|
| FR-001 | Organizaciones y proyectos | Crear organizaciones, proyectos, miembros y roles                     | P0            |
| FR-002 | Conexión GitHub            | Instalar GitHub App, listar repos autorizados y seleccionar PR/branch | P0            |
| FR-003 | Registro de URL            | Crear target web con ambiente, credenciales y límites                 | P0            |
| FR-004 | Run orchestration          | Crear, pausar, reanudar, cancelar y reintentar runs                   | P0            |
| FR-005 | Live agent feed            | Mostrar estado, tarea, evidencia y dependencias de cada agente        | P0            |
| FR-006 | Risk planning              | Generar plan basado en diff, stack, criticidad y policies             | P0            |
| FR-007 | Browser testing            | Descubrir y ejecutar flujos Playwright con trazas                     | P0            |
| FR-008 | Security checks            | Ejecutar al menos SAST/secret/web headers según fuente                | P0            |
| FR-009 | Performance checks         | Ejecutar smoke y métricas base; soportar k6                           | P0            |
| FR-010 | Accessibility              | Ejecutar axe y checks de teclado configurables                        | P0            |
| FR-011 | Test execution             | Detectar y ejecutar tests existentes sin modificar el repositorio     | P0            |
| FR-012 | Evidence model             | Guardar evidencia normalizada y artefactos                            | P0            |
| FR-013 | Release score              | Calcular score con desglose y policy result                           | P0            |
| FR-014 | GitHub Check               | Publicar summary y annotations                                        | P1            |
| FR-015 | Results publishing         | Publicar reporte o GitHub Check sin escribir código ni modificar PRs  | P1            |
| FR-016 | Policies                   | Configurar reglas por severidad, cobertura, ambiente y agente         | P1            |
| FR-017 | Baselines                  | Comparar métricas y comportamiento contra runs anteriores             | P1            |
| FR-018 | Knowledge citations        | Mostrar fuente/version de recomendaciones técnicas                    | P1            |
| FR-019 | Tool health                | Mostrar versiones y salud de conectores                               | P1            |
| FR-020 | Custom MCP                 | Registrar MCP privado enterprise con aprobación                       | P2            |
| FR-021 | Self-hosted runner         | Ejecutar workers dentro de red del cliente                            | P2            |
| FR-022 | Billing                    | Planes, límites, metering y facturación                               | P2            |

# 18. Requisitos no funcionales

| **ID**  | **Categoría**    | **Requisito**                                                                       |
|---------|------------------|-------------------------------------------------------------------------------------|
| NFR-001 | Disponibilidad   | Control plane objetivo 99.9% post-beta; degradación elegante ante fallo de LLM/tool |
| NFR-002 | Escalabilidad    | Workers horizontales y colas; sin estado local persistente                          |
| NFR-003 | Seguridad        | Cifrado en tránsito y reposo, RBAC, scopes mínimos y audit logs                     |
| NFR-004 | Aislamiento      | Cada run en workspace/contendor aislado con red restringida                         |
| NFR-005 | Explicabilidad   | Decisiones de release enlazadas a evidencia y policy version                        |
| NFR-006 | Reproducibilidad | Commit, herramientas, configuración y ambiente identificados                        |
| NFR-007 | Latencia         | Primer feedback visible \<30 s para PR pequeño; streaming continuo                  |
| NFR-008 | Observabilidad   | Trazas por run, agente, tool call y LLM call                                        |
| NFR-009 | Portabilidad     | Adaptadores para proveedor LLM, DB, cache y ejecución                               |
| NFR-010 | Privacidad       | Retención configurable; no entrenar modelos con datos del cliente                   |
| NFR-011 | Accesibilidad    | Dashboard objetivo WCAG 2.2 AA                                                      |
| NFR-012 | Costo            | Presupuesto por run y cancelación automática por límite                             |

# 19. Modelos de datos

## 19.1 Entidades principales

| **Entidad**         | **Campos clave**                                                      |
|---------------------|-----------------------------------------------------------------------|
| Organization        | id, name, plan, region, policies, billing_customer_id                 |
| Project             | id, organization_id, name, source_type, default_policy_id             |
| Connector           | id, type, encrypted_secret_ref, scopes, status, metadata              |
| Target              | id, project_id, repo_ref/url/environment/container_ref                |
| Run                 | id, trigger, status, commit_sha, policy_version, score, timestamps    |
| AgentTask           | id, run_id, agent_type, status, inputs_ref, outputs_ref, retry_count  |
| CapabilityExecution | id, capability, tool_adapter, version, status, timing, cost           |
| Finding             | id, category, severity, confidence, title, evidence_refs, fingerprint |
| Artifact            | id, type, s3_uri, hash, retention, redaction_status                   |
| Policy              | id, version, gates, autonomy, limits, approvals                       |
| ToolDefinition      | id, versions, capabilities, health, source_snapshot                   |
| KnowledgeSource     | id, publisher, url, version, retrieved_at, hash                       |
| Approval            | id, action, requester, approver, status, rationale                    |

## 19.2 Finding schema

{  
"finding_id": "uuid",  
"category": "security\|functional\|performance\|accessibility\|reliability",  
"severity": "critical\|high\|medium\|low\|info",  
"confidence": 0.93,  
"title": "Session cookie missing SameSite",  
"observation": "Captured Set-Cookie header lacks SameSite",  
"impact": "Increases CSRF exposure depending on flow",  
"evidence": \[{"artifact_id":"...", "locator":"header:Set-Cookie"}\],  
"reproduction_steps": \["Open /login", "Authenticate", "Inspect response"\],  
"recommendation": "Set SameSite=Lax or Strict after compatibility review",  
"source_refs": \["knowledge://owasp/snapshot/..."\],  
"tool": {"id":"playwright", "version":"..."},  
"environment_fingerprint": "sha256:...",  
"fingerprint": "dedupe-hash"  
}

# 20. Release Confidence Score

El score debe ser explicable y no confundirse con una garantía. Combina cumplimiento de policy, severidad, cobertura ejecutada, confiabilidad de herramientas, evidencia y riesgo del cambio.

## 20.1 Componentes iniciales

| **Componente**         | **Peso inicial** | **Notas**                                              |
|------------------------|------------------|--------------------------------------------------------|
| Functional correctness | 25%              | Resultados de unit/integration/E2E y critical journeys |
| Regression risk        | 15%              | Diferencias contra baseline y blast radius             |
| Security               | 20%              | Hallazgos, exploitability segura y policy              |
| Performance            | 15%              | SLOs, Web Vitals y comparación                         |
| Accessibility          | 10%              | Violaciones y criticidad                               |
| Reliability/chaos      | 10%              | Reintentos, idempotencia, fallos controlados           |
| Evidence completeness  | 5%               | Cobertura del plan y salud de herramientas             |

## 20.2 Resultado

- 90-100: Ready, sujeto a gates obligatorios.

- 75-89: Conditional; revisar riesgos señalados.

- 50-74: Manual review required.

- 0-49: Blocked.

- Cualquier gate crítico puede bloquear aunque el promedio sea alto.

# 21. Seguridad, privacidad y uso responsable

## 21.1 Amenazas específicas

- Prompt injection en código, issues, páginas web o documentación.

- Exfiltración de secretos mediante logs, prompts o artefactos.

- Ejecución arbitraria de código del repositorio.

- SSRF desde browser/HTTP workers.

- Pruebas destructivas sobre sistemas no autorizados.

- Contaminación cruzada entre tenants.

- MCP/tool server comprometido.

- Resultados falsificados o evidencia incompleta.

- Supply-chain risk de dependencias y contenedores.

## 21.2 Controles

| **Control**              | **Implementación**                                                                      |
|--------------------------|-----------------------------------------------------------------------------------------|
| Sandbox                  | Contenedores efímeros, usuario no root, filesystem temporal, límites CPU/memoria/tiempo |
| Network policy           | Allowlist por target, bloqueo metadata endpoints y rangos privados no autorizados       |
| Secrets                  | AWS Secrets Manager, inyección runtime, redacción y nunca en contexto LLM               |
| Authorization            | GitHub App scopes mínimos; RBAC por organización y proyecto                             |
| Tool signing             | Imágenes y adaptadores versionados, hashes y SBOM                                       |
| Prompt injection defense | Separación instrucciones/datos, content labeling, tool allowlist y output validation    |
| Auditability             | Log inmutable de decisiones, tool calls, approvals y policy versions                    |
| Data retention           | Políticas por plan; borrado verificable y exportación                                   |
| Abuse prevention         | Verificación de dominio/autorización y límites para carga/chaos/security                |

# 22. Observabilidad y evaluación

## 22.1 Telemetría

- Trace ID por QA Run y spans por agente, capability, tool y LLM.

- Métricas: latencia, tokens, costo, retries, cache hit, failures, findings y duration.

- Logs estructurados con redacción automática.

- Health dashboard de proveedores y tools.

- Replay de runs utilizando artefactos y versiones guardadas.

## 22.2 Evaluación de agentes

| **Dimensión**    | **Métrica**                                                 |
|------------------|-------------------------------------------------------------|
| Exactitud        | Precision/recall de hallazgos en repos benchmark            |
| Utilidad         | Tasa de findings aceptados; tests/PRs adoptados             |
| Reproducibilidad | Porcentaje de hallazgos reproducibles                       |
| Alucinación      | Afirmaciones sin evidencia por run                          |
| Eficiencia       | Costo y tiempo por riesgo detectado                         |
| Cobertura        | Critical journeys y superficies ejecutadas                  |
| Colaboración     | Verificaciones cruzadas que cambian confianza correctamente |
| Estabilidad      | Runs exitosos y fallos recuperados                          |

# 23. UX y experiencia visual

## 23.1 Pantallas

- Onboarding: crear organización, conectar GitHub y registrar URL.

- Projects: targets, últimos runs, score y tendencia.

- New Run: elegir fuente, alcance, policy, profundidad de pruebas y presupuesto.

- Mission Control: grafo de agentes, estados, dependencias y eventos en streaming.

- Findings: filtros, evidencia, reproducción, severidad y owner.

- Artifacts: screenshots, traces, videos, logs y resultados de herramientas.

- Release Decision: score, gates, riesgos residuales y recomendación.

- Tool Center: herramientas, versiones, salud y capacidades.

- Knowledge Center: fuentes oficiales, snapshots y fecha de actualización.

- Settings: policies, scopes, retention, budgets, model providers y notifications.

## 23.2 Personalidad controlada

Las personalidades aparecen en mensajes de progreso no críticos. Las decisiones, reportes y alertas mantienen lenguaje profesional. Ejemplo del Chaos Engineer: “Encontré otra forma segura de romper el checkout 😈”; seguido por evidencia, impacto y reproducción formales.

# 24. API y eventos

## 24.1 Endpoints iniciales

POST /v1/projects  
POST /v1/connectors/github/install  
POST /v1/targets/repository  
POST /v1/targets/web  
POST /v1/runs  
GET /v1/runs/{run_id}  
POST /v1/runs/{run_id}/cancel  
POST /v1/runs/{run_id}/approve  
GET /v1/runs/{run_id}/events  
GET /v1/runs/{run_id}/findings  
GET /v1/runs/{run_id}/artifacts  
POST /v1/runs/{run_id}/publish-github-check  
GET /v1/tools  
GET /v1/knowledge/sources

## 24.2 Eventos

run.created  
run.planned  
agent.started  
agent.message.sent  
capability.execution.started  
tool.execution.completed  
finding.created  
finding.verified  
approval.required  
release.decision.created  
run.completed  
run.failed

# 25. Estructura del repositorio para vibe coding

swarm-ai-qa/  
├── apps/  
│ ├── web/ \# Next.js dashboard  
│ └── api/ \# FastAPI control plane  
├── packages/  
│ ├── agent-sdk/ \# contratos, base classes, schemas  
│ ├── orchestration/ \# LangGraph graphs/subgraphs  
│ ├── capabilities/ \# capability definitions  
│ ├── tool-registry/ \# registry + selection policies  
│ ├── llm-gateway/ \# providers, retry, budgets, validation  
│ ├── knowledge-hub/ \# ingestion, RAG, provenance  
│ ├── evidence-model/ \# findings/artifacts normalization  
│ ├── policy-engine/ \# release gates and autonomy  
│ └── shared-types/ \# OpenAPI/JSON schemas  
├── agents/  
│ ├── qa-director/  
│ ├── test-architect/  
│ ├── repository-analyst/  
│ ├── browser-engineer/  
│ ├── security-engineer/  
│ ├── performance-engineer/  
│ ├── accessibility-specialist/  
│ ├── regression-analyst/  
│ ├── chaos-engineer/  
│ └── release-manager/  
├── workers/  
│ ├── browser-worker/  
│ ├── scanner-worker/  
│ ├── performance-worker/  
│ └── test-runner-worker/  
├── adapters/  
│ ├── github/  
│ ├── playwright/  
│ ├── semgrep/  
│ ├── gitleaks/  
│ ├── k6/  
│ ├── axe/  
│ └── docker/  
├── infra/  
│ ├── docker/  
│ ├── terraform/  
│ └── aws/  
├── prompts/ \# versionados; no lógica oculta  
├── policies/  
├── schemas/  
├── evals/  
├── tests/  
├── docs/  
│ ├── adr/  
│ ├── runbooks/  
│ └── product/  
└── .kiro/ \# specs, steering y context files

# 26. Reglas para vibe coding

51. El PRD es la fuente principal de intención; los ADR mandan sobre decisiones posteriores.

52. Ningún agente o adaptador se implementa sin schema de entrada y salida.

53. No mezclar razonamiento LLM con ejecución de herramientas en la misma función.

54. Toda llamada externa debe tener timeout, retry clasificado e idempotencia cuando aplique.

55. Usar tipos estrictos: Pydantic en backend y TypeScript generado desde OpenAPI.

56. No guardar secretos en repo, logs, prompts o fixtures.

57. Agregar test unitario a capability selection y parsing de herramientas.

58. Cada feature incluye happy path, failure path y observabilidad.

59. Preferir vertical slices demostrables sobre capas incompletas.

60. No introducir una nueva dependencia sin justificarla en ADR.

61. Los prompts se versionan, prueban y revisan como código.

62. Cada tool adapter debe tener un smoke test ejecutable.

63. La UI nunca debe mostrar actividad ficticia; cada estado proviene de eventos reales.

64. No hardcodear proveedor LLM, tool version ni repositorio demo.

65. Todo output LLM crítico se valida contra JSON Schema y reglas deterministas.

## 26.1 Definition of Done

- Funcionalidad accesible desde UI o API.

- Tests mínimos verdes.

- Errores visibles y recuperables.

- Trazas y métricas disponibles.

- Sin secretos ni datos sensibles expuestos.

- Documentación y schema actualizados.

- Demo reproducible desde ambiente limpio.

# 27. Plan de construcción: 20-27 de julio de 2026

| **Fecha** | **Objetivo**  | **Entregable**                                                       |
|-----------|---------------|----------------------------------------------------------------------|
| 20 jul    | Fundación     | Repo, monorepo, PRD, ADR-001, diseño UI, Neon, auth y skeleton API   |
| 21 jul    | Control plane | Projects, targets, runs, event stream y LangGraph mínimo             |
| 22 jul    | GitHub path   | GitHub connector, clone/diff, Repository Analyst y Test Architect    |
| 23 jul    | Web path      | Playwright worker, URL target, screenshots/traces y Browser Agent    |
| 24 jul    | Specialists   | Security básico, accessibility axe y performance smoke k6/Lighthouse |
| 25 jul    | Intelligence  | Colaboración entre agentes, evidence model, score y report           |
| 26 jul    | Hardening     | Retries, cache, guardrails, demo repo/app, tests y observability     |
| 27 jul    | Submission    | Deploy, video, pitch, documentación, fallback demo y entrega         |

## 27.1 Camino crítico

- Run state + event streaming.

- GitHub PR ingestion.

- Playwright worker reproducible.

- Evidence model común.

- Release decision visible.

- Demo estable y preparada para fallos de API.

## 27.2 Funciones recortables sin romper la visión

- La generación de código, patches y PRs queda excluida permanentemente del producto.

- k6 puede limitarse a smoke test.

- Security puede comenzar con headers + secret scan.

- Knowledge Hub puede usar snapshots manuales oficiales en lugar de crawler automático.

- Billing y marketplace quedan diseñados, no implementados.

# 28. Estrategia de demo

## 28.1 Guion de 4-5 minutos

66. Presentar el problema: QA fragmentado y costoso.

67. Conectar PR GitHub con un defecto intencional.

68. Mostrar al QA Director crear un plan y lanzar agentes.

69. Visualizar Repository, Security, Browser, Accessibility y Performance trabajando.

70. Mostrar colaboración: un hallazgo confirmado por otro agente.

71. Introducir la URL de la app y reproducir el defecto con trace/screenshot.

72. Mostrar score, decisión “Blocked” y riesgo residual.

73. Abrir el reporte final y recorrer evidencia, reproducción y recomendación de release.

74. Cerrar con la visión: el mismo sistema se extiende a Docker, cloud y entornos privados.

## 28.2 Demo de respaldo

- Run pregrabado y artefactos locales si falla una API externa.

- Modo mock explícitamente marcado para UI, nunca presentado como ejecución real.

- Repositorio y aplicación demo propios, deterministas y desplegados.

- Video corto de respaldo.

- LLM fallback y respuestas cacheadas por input exacto para el flujo demo.

# 29. Modelo de negocio

La suscripción es viable, pero debe combinarse con uso medido porque los costos dependen de tokens, minutos de navegador, CPU de workers, almacenamiento y carga. El pricing definitivo requiere validación de mercado.

| **Plan conceptual** | **Cliente**                | **Incluye**                                                  | **Métrica de límite**           |
|---------------------|----------------------------|--------------------------------------------------------------|---------------------------------|
| Free / Open Source  | Individuos y proyectos OSS | Repos públicos, runs limitados, reportes básicos             | Runs + minutos de ejecución     |
| Pro                 | Desarrolladores            | Repos privados, historial, PR checks y modelos configurables | Créditos mensuales              |
| Team                | Startups/equipos           | Concurrencia, policies, colaboración y CI/CD                 | Créditos + agentes concurrentes |
| Business            | Empresas medianas          | SSO, retención, controles y reporting                        | Uso comprometido                |
| Enterprise          | Corporativos               | VPC/self-hosted, custom MCP, SLA, audit y soporte            | Contrato anual                  |

## 29.1 Métricas de facturación candidatas

- Minutos de execution worker.

- QA Runs y agentes concurrentes.

- Tokens/model credits.

- Almacenamiento y retención de artefactos.

- Número de proyectos/targets activos.

- Enterprise connectors y self-hosted runners.

# 30. Métricas de producto y negocio

| **Categoría** | **Métricas**                                                                  |
|---------------|-------------------------------------------------------------------------------|
| North Star    | Cambios enviados con evidencia de Swarm y sin incidente atribuible detectable |
| Activation    | Primer repo conectado + primer run completado                                 |
| Engagement    | Runs por proyecto/semana; critical journeys mantenidos                        |
| Value         | Bugs válidos detectados; tiempo ahorrado; findings reproducibles aceptados    |
| Quality       | False positive rate; reproducibility rate; hallucination rate                 |
| Reliability   | Run success rate; provider/tool failure recovery                              |
| Business      | Conversion, expansion, gross margin, retention y usage growth                 |
| Cost          | Costo por run, por finding válido y por organización                          |

# 31. Riesgos y mitigaciones

| **Riesgo**                   | **Impacto**                        | **Mitigación**                                                           |
|------------------------------|------------------------------------|--------------------------------------------------------------------------|
| Alcance excesivo             | No completar experiencia coherente | Vertical slices; P0 estricto; demo GitHub + URL                          |
| Alucinación LLM              | Pérdida de confianza               | Evidence-first, schemas, deterministic gates y citations                 |
| Cuotas de Gemini             | Runs interrumpidos                 | Concurrency control, cache, backoff, circuit breaker y fallback aprobado |
| Herramientas desactualizadas | Comandos/diagnósticos incorrectos  | Tool Registry, pinned versions, official sources y compatibility tests   |
| Ejecución insegura           | Daño o fuga de datos               | Sandbox, network policies, scopes y approvals                            |
| Falsos positivos             | Fatiga y churn                     | Confidence, dedupe, baselines y feedback loop                            |
| Demo dependiente de internet | Fallo de presentación              | Precomputed artifacts, deterministic target y video backup               |
| Costo de infraestructura     | Margen negativo                    | Budgets, metering, tiers de modelos y sampling                           |
| Competencia consolidada      | Difícil diferenciación             | Correlación multiagente, runtime+code y release decision                 |
| Privacidad enterprise        | Bloqueo de ventas                  | Self-hosted runners, data controls y VPC roadmap                         |

# 32. Investigación obligatoria

## 32.1 Producto y mercado

- Entrevistar al menos 10 perfiles: devs, founders, QA, SDET y engineering managers.

- Validar qué evento dispara compra: PR review, release gate, auditoría o monitoring.

- Comparar pricing y límites de competidores de testing, security y AI coding.

- Medir disposición de pago por ejecución vs suscripción.

- Descubrir integraciones imprescindibles por segmento.

## 32.2 Técnica

| **Tema**    | **Preguntas a resolver**                                                                              |
|-------------|-------------------------------------------------------------------------------------------------------|
| LangGraph   | Checkpointing, parallel fan-out, cancellation, interrupts, durable runs y streaming UI                |
| Gemini      | Rate limits reales del proyecto, structured outputs, function calling, caching, latency y data policy |
| Neon        | pgvector performance, branching, pooling, limits y migration path                                     |
| MCP         | Trust model, auth, tool discovery, transport y private server onboarding                              |
| Sandbox     | Nivel de aislamiento requerido para repos no confiables                                               |
| Playwright  | Credential handling, route discovery, trace size y deterministic selectors                            |
| Security    | Qué pruebas pueden ejecutarse legalmente y sin impacto en producción                                  |
| Performance | Safe defaults, SLO ingestion y distributed load roadmap                                               |
| Scoring     | Calibración del score y prevención de falsa precisión                                                 |
| Knowledge   | Licencias, ingestion cadence, provenance y prompt injection defense                                   |

## 32.3 Legal y compliance

- Términos de uso de modelos y herramientas.

- Consentimiento y autorización de pruebas sobre dominios.

- DPA, privacidad, retención y subprocessors.

- Licencias de documentación indexada y reglas de scanners.

- Políticas de responsible disclosure.

- Ruta SOC 2, ISO 27001 y controles enterprise.

# 33. Roadmap de producto

| **Fase**          | **Horizonte**  | **Contenido**                                                              |
|-------------------|----------------|----------------------------------------------------------------------------|
| Hackathon Release | 20-27 jul 2026 | GitHub + web URL, 5-7 agentes visibles, evidence, score y demo             |
| Private Alpha     | 0-6 semanas    | GitHub App robusta, policies, baselines, billing simple y feedback         |
| Public Beta       | 2-4 meses      | GitLab, OpenAPI, equipos, scheduled runs y reportes comparativos            |
| V1 Commercial     | 4-8 meses      | Self-hosted runner, SSO, enterprise audit y reliability                    |
| Expansion         | 8-18 meses     | Docker/Kubernetes/AWS, custom MCP marketplace y observability integrations |
| Platform          | 18+ meses      | Swarm Security, DevOps y Architecture sobre el mismo core                  |

# 34. Criterios de aceptación de la primera entrega

75. Un usuario puede crear proyecto y conectar un repositorio GitHub.

76. El sistema puede crear un run para un PR o rama.

77. El QA Director produce un plan estructurado y ejecuta al menos tres especialistas.

78. Un repositorio se clona y analiza en entorno aislado.

79. Una URL puede explorarse con Playwright y genera evidencia real.

80. Al menos una auditoría de seguridad, rendimiento y accesibilidad produce resultados estructurados.

81. Al menos dos agentes colaboran mediante un mensaje dirigido y la verificación afecta la confianza.

82. La UI muestra actividad real en streaming.

83. El reporte contiene findings, reproducción, evidencia y score.

84. El sistema tolera al menos un fallo de proveedor mediante retry/fallback o degradación visible.

85. La demo puede ejecutarse nuevamente desde un ambiente limpio.

86. No se exponen secrets en UI, logs ni artefactos.

# 35. Decisiones abiertas

| **Decisión**       | **Recomendación provisional**                     | **Fecha límite**      |
|--------------------|---------------------------------------------------|-----------------------|
| Proveedor Redis    | Upstash para velocidad; ElastiCache en enterprise | 21 jul                |
| Auth               | Clerk/Auth.js vs Cognito                          | 21 jul                |
| LLM fallback       | Definir segundo proveedor/modelo autorizado       | 22 jul                |
| GitHub integration | GitHub App vs PAT para demo                       | 21 jul                |
| Worker runtime     | ECS Fargate vs local Docker para hackathon        | 22 jul                |
| Report format      | Dashboard + export PDF posterior                  | 24 jul                |
| Scoring weights    | Usar pesos iniciales y marcar experimental        | 25 jul                |
| Nombre legal/marca | Validación de disponibilidad de Swarm AI QA       | Después del hackathon |

# 36. Architecture Decision Records iniciales

| **ADR** | **Decisión**                                                             |
|---------|--------------------------------------------------------------------------|
| ADR-001 | Usar arquitectura multiagente jerárquica con QA Director y especialistas |
| ADR-002 | Usar LangGraph para orquestación y estado durable                        |
| ADR-003 | Desacoplar agentes de herramientas mediante Capability Manager           |
| ADR-004 | Desacoplar agentes de modelos mediante LLM Provider Gateway              |
| ADR-005 | Usar Neon PostgreSQL + pgvector como almacenamiento inicial              |
| ADR-006 | Usar cache/colas Redis-compatible                                        |
| ADR-007 | Ejecutar repos no confiables en workers aislados                         |
| ADR-008 | Evidence-first y schemas estructurados como requisito                    |
| ADR-009 | GitHub + URL web como first vertical slice                               |
| ADR-010 | Gemini 3.1 Flash-Lite como modelo inicial, sin dependencia rígida        |
| ADR-012 | Mantener Swarm AI QA read-only respecto al código y entregar solo resultados de QA |

# 37. Referencias oficiales consultadas

- [<u>Google AI for Developers — Gemini 3.1 Flash-Lite</u>](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)

- [<u>Google AI for Developers — Gemini API rate limits</u>](https://ai.google.dev/gemini-api/docs/rate-limits)

- [<u>LangChain — LangGraph overview</u>](https://docs.langchain.com/oss/python/langgraph/overview)

- [<u>LangChain — Multi-agent systems</u>](https://docs.langchain.com/oss/python/langchain/multi-agent/index)

- [<u>LangChain — Router pattern</u>](https://docs.langchain.com/oss/python/langchain/multi-agent/router)

- [<u>LangChain — Subagents pattern</u>](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)

- [<u>Grafana — k6 documentation</u>](https://grafana.com/docs/k6/latest/)

- [<u>Playwright documentation</u>](https://playwright.dev/docs/intro)

- [<u>Model Context Protocol documentation</u>](https://modelcontextprotocol.io/)

- [<u>Neon — pgvector documentation</u>](https://neon.com/docs/extensions/pgvector)

- [<u>OWASP</u>](https://owasp.org/)

- [<u>Semgrep documentation</u>](https://semgrep.dev/docs/)

Nota: las versiones de herramientas no se fijan en este PRD. El Tool Registry conservará las versiones exactas utilizadas por cada ejecución y su fecha de verificación.

# Apéndice A. Plantilla de especificación de agente

agent_id: security_test_engineer  
version: 1.0.0  
role: Application Security Test Engineer  
goal: Detectar y verificar riesgos de seguridad con evidencia reproducible.  
inputs:  
- TestPlanV1  
- RepositoryContextV1  
- RuntimeTargetV1  
outputs:  
- FindingV1\[\]  
- VerificationRequestV1\[\]  
allowed_capabilities:  
- static_security_scan  
- secret_scan  
- dependency_scan  
- header_audit  
forbidden_capabilities:  
- destructive_exploit  
- unrestricted_network  
knowledge_scopes:  
- OWASP  
- CWE  
confidence_policy:  
critical_minimum: 0.90  
escalation:  
low_confidence: qa_director  
runtime_verification: browser_automation_engineer  
personality: Paranoico, conciso y basado en evidencia.  
output_schema: SecurityAgentOutputV1

# Apéndice B. Plantilla de prompt de sistema

ROLE  
You are the {role} inside Swarm AI QA.  
  
MISSION  
{goal}  
  
CONSTITUTION  
- Never invent tool results.  
- Separate observations from inferences.  
- Cite evidence references for every material finding.  
- Use only allowed capabilities.  
- Escalate uncertainty according to policy.  
  
AVAILABLE CONTEXT  
{scoped_context}  
  
AVAILABLE CAPABILITIES  
{capability_descriptions}  
  
OUTPUT  
Return valid JSON matching {output_schema}. No prose outside JSON.

# Apéndice C. Checklist de lanzamiento

- Branding y dominio revisados.

- GitHub App permissions revisados.

- Demo repository y web target deterministas.

- All agents and tools show real status.

- Fallback and demo backup tested.

- Security and privacy statement available.

- Pitch deck, video and README aligned with PRD.

- No secret or customer data in screenshots.

- Exact model identifier and tool versions documented.

- Post-hackathon backlog created from P1/P2 items.

| **Baseline aprobado —** Este documento define la visión de startup y el contrato inicial de construcción. Durante la semana del hackathon, la prioridad es implementar una experiencia vertical completa y verificable, conservando interfaces que permitan expandir el producto después de la entrega. |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
