from typing import Protocol

from .models import ApiWorkerRequestV1, ApiWorkerResultV1


class ApiWorker(Protocol):
    async def run(
        self,
        request: ApiWorkerRequestV1,
    ) -> ApiWorkerResultV1: ...
