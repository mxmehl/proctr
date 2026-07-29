"""Concurrent PR fetching across all repos for a given forge."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from proctr.forges.base import Forge, PullRequest
    from proctr.projects import Repo

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


def _fetch_one(repo: Repo, resolve_forge: Callable[[Repo], Forge]) -> list[PullRequest]:
    """Resolve the right forge for a repo and fetch its PRs (may raise)."""
    forge = resolve_forge(repo)
    return forge.list_matching_prs(repo)


def fetch_all_prs(
    repos: list[Repo],
    resolve_forge: Callable[[Repo], Forge],
    *,
    max_workers: int = MAX_WORKERS,
) -> FetchResult:
    """Fetch PRs for all repos in parallel, isolating per-repo failures.

    resolve_forge maps each repo to the Forge adapter that should handle
    it (e.g. by repo.forge + repo.host), so a single call can span
    multiple forges and multiple instances of the same forge software.
    Raising from resolve_forge (e.g. "no credentials configured for this
    host") is treated the same as any other per-repo failure.
    """
    pull_requests: list[PullRequest] = []
    errors: list[FetchError] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {executor.submit(_fetch_one, repo, resolve_forge): repo for repo in repos}
        for future in as_completed(future_to_repo):
            repo = future_to_repo[future]
            try:
                pull_requests.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - isolate per-repo failures
                errors.append(FetchError(repo=repo, error=str(exc)))

    return FetchResult(pull_requests=pull_requests, errors=errors)
