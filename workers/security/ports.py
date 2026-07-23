from typing import Protocol

from .models import SecurityWorkerRequestV1, SecurityWorkerResultV1


class SecurityWorker(Protocol):
    async def run(
        self,
        request: SecurityWorkerRequestV1,
    ) -> SecurityWorkerResultV1: ...
