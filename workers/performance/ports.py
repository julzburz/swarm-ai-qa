from typing import Protocol

from .models import PerformanceWorkerRequestV1, PerformanceWorkerResultV1


class PerformanceWorker(Protocol):
    async def run(
        self,
        request: PerformanceWorkerRequestV1,
    ) -> PerformanceWorkerResultV1: ...
