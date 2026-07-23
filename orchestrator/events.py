from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

from .models import RunEventType, RunEventV1
from .store import RunStore


TERMINAL_EVENTS = {
    RunEventType.RUN_COMPLETED,
    RunEventType.RUN_FAILED,
    RunEventType.RUN_CANCELLED,
}


class EventStream:
    """Historial durable más suscripción en vivo, listo para SSE."""

    def __init__(self, store: RunStore) -> None:
        self._store = store
        self._subscribers: dict[UUID, list[asyncio.Queue[RunEventV1]]] = defaultdict(list)

    async def publish(self, event: RunEventV1) -> RunEventV1:
        stored = self._store.append_event(event)
        for queue in tuple(self._subscribers.get(stored.run_id, [])):
            await queue.put(stored)
        return stored

    async def subscribe(
        self,
        run_id: UUID,
        after_sequence: int = 0,
    ) -> AsyncIterator[RunEventV1]:
        queue: asyncio.Queue[RunEventV1] = asyncio.Queue()
        self._subscribers[run_id].append(queue)
        last_sequence = after_sequence
        try:
            for event in self._store.list_events(run_id, after_sequence):
                if event.sequence is not None and event.sequence > last_sequence:
                    last_sequence = event.sequence
                    yield event
                if event.event_type in TERMINAL_EVENTS:
                    return
            while True:
                event = await queue.get()
                if event.sequence is not None and event.sequence <= last_sequence:
                    continue
                if event.sequence is not None:
                    last_sequence = event.sequence
                yield event
                if event.event_type in TERMINAL_EVENTS:
                    return
        finally:
            self._subscribers[run_id].remove(queue)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]
