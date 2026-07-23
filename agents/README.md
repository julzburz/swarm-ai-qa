# Perfiles de agentes de Swarm AI QA

Este directorio convierte el catálogo conceptual del PRD en contratos implementables. Cada perfil define qué puede decidir un agente, qué contexto recibe, qué capacidades puede solicitar y qué evidencia debe producir.

## Principio de ejecución

Un agente no es un personaje visual ni un prompt aislado. En Swarm AI QA es una unidad de decisión con:

- contexto limitado a su misión;
- entradas y salidas estructuradas;
- capacidades y prohibiciones explícitas;
- estado y eventos auditables;
- criterios de confianza y escalamiento;
- obligación de enlazar evidencia real.

Los agentes pueden compartir el mismo proceso y proveedor LLM durante el hackathon. Su independencia proviene de sus contratos, contextos, herramientas y estados, no de desplegarlos como microservicios separados.

## Límite permanente: QA read-only

Swarm AI QA prueba, explora, intenta romper de forma autorizada y entrega resultados. Ningún
agente genera, modifica, aplica o propone código fuente, código de prueba ejecutable, fixes,
patches, commits, branches o pull requests. Test Architect puede producir matrices, casos y
Gherkin como documentación QA, nunca como archivos dentro del repositorio evaluado. GitHub
funciona como fuente de lectura y, con autorización opcional, como canal para publicar un Check
con los resultados.

## Estados de entrega

| Estado | Significado |
|---|---|
| `hackathon_core` | Necesario para demostrar la promesa principal. |
| `hackathon_conditional` | Se activa solamente para una misión o riesgo relevante. |
| `post_hackathon` | Perfil diseñado, pero su ejecución completa no bloquea la demo. |

## Enjambre del hackathon

| Agente | Estado | Resultado principal |
|---|---|---|
| QA Director | Core | Plan de misión y coordinación del run |
| Repository Analyst | Core | Perfil tecnológico y mapa de impacto del cambio |
| Test Architect | Core | Estrategia y tareas ejecutables |
| Browser Automation Engineer | Core | Flujos web y evidencia Playwright |
| Security Test Engineer | Core | Hallazgos de seguridad verificables |
| Accessibility Specialist | Core | Auditoría axe y verificaciones asistidas |
| Performance Test Engineer | Conditional | Métricas Lighthouse y smoke seguro |
| API Test Engineer | Core | OpenAPI y validación GET/HEAD sin mutaciones |
| Release Manager | Core | Decisión explicable de release |
| Evidence & Reporting Analyst | Core | Normalización, deduplicación y reporte |
| Regression Analyst | Post-hackathon | Comparación con baselines históricos |
| Chaos & Resilience Engineer | Post-hackathon | Experimentos de fallo autorizados |
| Tool Intelligence Agent | Post-hackathon | Salud y actualización de adaptadores |
| Knowledge Curator | Post-hackathon | Fuentes oficiales versionadas |

## Flujo común

1. El QA Director interpreta la misión: tarea rápida, examen dirigido o examen completo.
2. Repository Analyst produce `ProjectProfileV1` y `ChangeImpactMapV1`.
3. Test Architect transforma riesgo y alcance en `TestPlanV1`.
4. Los especialistas ejecutan capacidades mediante workers y producen evidencia.
5. Evidence & Reporting normaliza y correlaciona los resultados.
6. Release Manager aplica gates deterministas cuando la misión solicita una decisión de release.

## Archivos

- `_profile_contract.yaml`: campos y políticas comunes.
- `qa_director.yaml`: interfaz inteligente y orquestador.
- `repository_analyst.yaml`: reconocimiento tecnológico y análisis del cambio.
- `test_architect.yaml`: estrategia de pruebas.
- Los demás archivos contienen los especialistas, reporting y gobierno de herramientas.

Los contratos del camino crítico están implementados como modelos Pydantic en [`../schemas/`](../schemas/README.md). Los perfiles `hackathon_core` y `hackathon_conditional` no contienen referencias de entrada o salida pendientes.
