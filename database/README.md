# Neon PostgreSQL

Neon es el store compartido para entornos desplegados. SQLite permanece como implementación local para tests rápidos.

## Configuración

1. Crear un proyecto y una base de datos en Neon.
2. Copiar `.env.example` a `.env` y pegar allí las credenciales recién creadas. `.env` está ignorado por Git y se carga localmente sin imprimir su contenido.
3. Configurar dos URLs:
   - `DATABASE_URL`: hostname Neon con `-pooler`, utilizado por FastAPI.
   - `DATABASE_DIRECT_URL`: hostname directo sin `-pooler`, utilizado por Alembic.
4. Ambas conexiones deben exigir TLS mediante `sslmode=require`.

Nunca se envía ninguna URL de base de datos al frontend ni a los agentes.

## Migraciones

```text
alembic upgrade head
```

Alembic utiliza únicamente `DATABASE_DIRECT_URL`. La aplicación se conecta mediante `DATABASE_URL`.

## Datos y artefactos

Neon almacena estado, eventos, tareas, findings, mensajes y metadatos. Screenshots, videos, traces y logs grandes pertenecen a S3; la tabla `artifacts` conserva su referencia, hash y estado de redacción.

## Streaming

`run_events` es el historial durable. `EventStream` publica en vivo por SSE y permite reconectar usando `after_sequence`. No se utiliza `LISTEN/NOTIFY` sobre la conexión pooled.

## Tablas iniciales

- `projects`
- `repository_targets`
- `runtime_targets`
- `missions`
- `runs`
- `run_tasks`
- `run_events`
- `agent_messages`
- `tool_executions`
- `findings`
- `finding_verifications`
- `artifacts`
- `release_decisions`
