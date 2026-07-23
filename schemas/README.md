# Schemas ejecutables

Los modelos Pydantic de este directorio son la fuente de verdad inicial para los mensajes del enjambre. Todos usan `extra="forbid"`: un agente no puede añadir campos inesperados ni devolver prosa fuera del contrato.

Los contratos no incluyen artefactos de código generado. Los outputs permitidos se limitan a resultados de QA, evidencia, métricas, pasos de reproducción, cobertura y recomendaciones.

## Módulos

| Módulo | Contratos principales |
|---|---|
| `common.py` | enums, autorización, presupuesto, runtime y referencias de evidencia |
| `project.py` | GitHub, pull requests, tecnologías, monorepos y mapa de impacto |
| `mission.py` | tarea rápida, examen dirigido/completo y plan del QA Director |
| `execution.py` | plan de pruebas, tareas, journeys y cobertura |
| `evidence.py` | ejecución de herramientas, findings y verificación cruzada |
| `specialists.py` | tareas y outputs de Browser, Security, Accessibility, Performance y API |
| `release.py` | policies, gates, score y decisión de release |
| `reporting.py` | reporte del run y resumen para GitHub Checks |

## Reglas relevantes

- Una misión requiere repositorio, runtime o ambos.
- `quick_task` admite exactamente uno o dos trabajos.
- Un target de producción no puede habilitar load ni chaos testing.
- Una tecnología `confirmed` requiere confianza mínima de 0.90 y evidencia.
- Un finding High requiere confianza mínima de 0.80; Critical requiere 0.90.
- Un hallazgo confirmado debe indicar un agente verificador diferente.
- Un tool error nunca puede representarse como ejecución exitosa.
- Un gate evaluado debe enlazar evidencia.
- Los pesos del score deben sumar 1.0.
- Un gate bloqueante fallido obliga a una decisión `blocked`.

## Exportación futura

Cuando se cree la API FastAPI, sus endpoints utilizarán estos modelos directamente. FastAPI generará OpenAPI y los tipos TypeScript del frontend se generarán desde ese documento para evitar contratos duplicados.
