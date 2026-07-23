from __future__ import annotations

from typing import Protocol

from .models import BrowserWorkerRequestV1, BrowserWorkerResultV1


class BrowserWorker(Protocol):
    async def run(self, request: BrowserWorkerRequestV1) -> BrowserWorkerResultV1: ...
