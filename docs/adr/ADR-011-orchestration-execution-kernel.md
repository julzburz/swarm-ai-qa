# ADR-011: Kernel de ejecución desacoplado del framework de agentes

- Estado: Aceptado para el vertical slice del hackathon
- Relacionado: ADR-001, ADR-002, ADR-003 y ADR-008

## Contexto

Los contratos de misión, evidencia y release deben conservarse aunque cambie el framework de orquestación. También necesitamos probar fan-out/fan-in, reintentos, cancelación y streaming antes de conectar LLMs y herramientas externas.

## Decisión

Implementar un kernel async pequeño detrás de puertos propios (`AgentExecutor`, `AgentRegistry`, `SQLiteRunStore` y `EventStream`). Los agentes no conocen el scheduler. LangGraph podrá envolver estos executors y asumir checkpointing avanzado sin modificar los contratos de dominio.

## Consecuencias

- Las reglas críticas del run pueden probarse sin red ni proveedor LLM.
- Mission Control recibe eventos reales desde el primer vertical slice.
- SQLite proporciona recuperación local para la demo.
- La integración LangGraph sigue pendiente y debe reutilizar estos puertos, no duplicar lógica de seguridad o schemas.
- Para operación distribuida habrá que sustituir el store y el event fan-out por implementaciones compartidas.
