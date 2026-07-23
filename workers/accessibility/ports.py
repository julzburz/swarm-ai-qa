from typing import Protocol

from .models import AccessibilityWorkerRequestV1, AccessibilityWorkerResultV1


class AccessibilityWorker(Protocol):
    async def run(
        self,
        request: AccessibilityWorkerRequestV1,
    ) -> AccessibilityWorkerResultV1: ...
