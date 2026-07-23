"""Read-only GitHub repository inspection adapter."""

from .client import GitHubApiError, GitHubReadClient, GitHubRestClient
from .models import GitHubInspectionV1

__all__ = ["GitHubApiError", "GitHubInspectionV1", "GitHubReadClient", "GitHubRestClient"]
