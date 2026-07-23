# ADR-012: Swarm AI QA es read-only respecto al código

- Estado: Aceptado
- Fecha: 20 de julio de 2026
- Tipo: Límite permanente de producto

## Contexto

Swarm AI QA representa un equipo autónomo de Quality Assurance, no un equipo de desarrollo. Su trabajo consiste en observar, ejecutar pruebas, explorar, intentar romper flujos dentro de límites autorizados, correlacionar evidencia y comunicar riesgos.

La generación de tests, fixes o pull requests confundiría su responsabilidad, ampliaría permisos de GitHub y haría menos claro el contrato de confianza con el usuario.

## Decisión

Los agentes nunca generan, editan, aplican ni proponen código fuente, tests, configuración, fixes, patches, commits, branches o pull requests.

Los repositorios son fuentes de solo lectura. Los workers pueden crear archivos efímeros internos necesarios para ejecutar herramientas, pero esos archivos:

- permanecen fuera del repositorio del usuario;
- no se presentan como código entregable;
- no se publican en GitHub;
- se eliminan con el workspace temporal.

Los únicos entregables del sistema son resultados de QA: findings, métricas, evidencias, pasos de reproducción, cobertura ejecutada, riesgos residuales, reportes y recomendaciones de release. Un GitHub Check autorizado se considera un canal de publicación del reporte, no una modificación de código.

## Consecuencias

- La GitHub App utiliza permisos de lectura más permiso opcional para Checks.
- Release Manager recomienda; no aprueba pipelines, fusiona ni despliega.
- Browser y API agents pueden ejecutar acciones seguras en entornos autorizados, pero no modificar el código.
- Toda capacidad de generación de tests, fixes, patches o PRs queda fuera del roadmap permanente.
- La interfaz evita botones como “Generate fix”, “Create PR” o “Apply patch”.
