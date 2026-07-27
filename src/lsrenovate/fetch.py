"""Concurrent PR fetching across all repos for a given forge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from lsrenovate.forges.base import Forge, PullRequest
from lsrenovate.projects import Repo

MAX_WORKERS = 8


@dataclass(frozen=True)
class FetchError:
    """A single repo's fetch failure, kept alongside successful results."""

    repo: Repo
    error: str


@dataclass(frozen=True)
class FetchResult:
    """Aggregated outcome of fetching PRs across many repos."""

    pull_requests: list[PullRequest]
    errors: list[FetchError]


def fetch_all_prs(
    repos: list[Repo], forge: Forge, *, max_workers: int = MAX_WORKERS
) -> FetchResult:
    """Fetch Renovate PRs for all repos in parallel, isolating per-repo failures."""
    pull_requests: list[PullRequest] = []
    errors: list[FetchError] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {executor.submit(forge.list_renovate_prs, repo): repo for repo in repos}
        for future in as_completed(future_to_repo):
            repo = future_to_repo[future]
            try:
                pull_requests.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - isolate per-repo failures
                errors.append(FetchError(repo=repo, error=str(exc)))

    return FetchResult(pull_requests=pull_requests, errors=errors)
