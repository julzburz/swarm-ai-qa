# Orquestador del QA Director

Este módulo implementa el kernel de ejecución del enjambre. Es independiente de FastAPI, del proveedor LLM y de las herramientas concretas.

## Componentes

| Archivo | Responsabilidad |
|---|---|
| `director.py` | Selección determinista de agentes, restricciones y grafo de tareas |
| `engine.py` | Scheduler async, dependencias, fan-out/fan-in, retries y cancelación |
| `events.py` | Historial y suscripción en vivo utilizable por SSE |
| `store.py` | Contrato común y checkpoints locales en SQLite |
| `neon_store.py` | Persistencia compartida de runs, tareas y eventos en Neon |
| `registry.py` | Registro explícito de executors por `agent_id` |
| `ports.py` | Protocolo que implementará cada agente real |
| `models.py` | Estado del run, records de tareas y eventos |

## Ciclo del run

```text
created → planned → running → completed
                         ├──→ failed
                         └──→ cancelling → cancelled
```

Dentro de `running`:

1. Se seleccionan tareas cuyas dependencias terminaron correctamente.
2. Se ejecutan hasta `budget.max_parallel_tasks` en paralelo.
3. Cada executor recibe únicamente los outputs de sus dependencias directas.
4. Los fallos transitorios se reintentan hasta el límite configurado.
5. Una dependencia fallida provoca `skipped`, nunca un resultado falso.
6. Reporting espera a los especialistas y Release Manager espera a Reporting.

## Conectar un agente real

Un adapter debe implementar `AgentExecutor`:

```python
class SecurityExecutor:
    agent_id = "security_test_engineer"

    async def execute(self, task, context):
        # Llamar capabilities/workers autorizados y validar SecurityAgentOutputV1.
        result = await security_agent.run(task, context)
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="SecurityAgentOutputV1",
            output=result.model_dump(mode="json"),
            evidence_refs=result.evidence_refs,
        )
```

El engine rechaza envelopes cuyo `run_id`, `task_id` o `agent_id` no coincide con la asignación.

## Integración con el frontend

El backend genera un UUID antes de iniciar la ejecución y lo pasa como `run_id`. Así Mission Control puede:

- consultar el checkpoint mientras el run continúa;
- suscribirse a `EventStream.subscribe(run_id, after_sequence)`;
- reconectarse usando el último `sequence` recibido;
- solicitar cancelación inmediata;
- recuperar el resultado después de reiniciar el proceso.

## Relación con LangGraph

Este kernel define el dominio y los puertos de ejecución; no reemplaza ADR-002. Los mismos executors y schemas podrán utilizarse como nodos de LangGraph. Mantener el scheduler aislado permite probar selección, seguridad, eventos y persistencia sin depender del framework ni mezclarlo con adaptadores de herramientas.

## Selección del store

- Tests y desarrollo sin red: `SQLiteRunStore`.
- Backend desplegado: `NeonRunStore.from_env()`.

Ambos implementan `RunStore`; el scheduler y los agentes no contienen lógica específica de la base de datos.
