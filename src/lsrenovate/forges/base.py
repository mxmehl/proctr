"""Forge-agnostic interface for listing and merging Renovate PRs.

Only GitHub is implemented today, but the interface is kept forge-agnostic
so gitlab (glab) and gitea (tea) adapters can be added later without
touching the app/UI layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from lsrenovate.projects import Repo


@dataclass(frozen=True)
class PullRequest:
    """A single open Renovate pull request."""

    repo: Repo
    number: int
    title: str
    url: str
    created_at: datetime
    updated_at: datetime
    mergeable: str
    merge_state_status: str


@dataclass(frozen=True)
class MergeResult:
    """Outcome of a single merge attempt."""

    pull_request: PullRequest
    success: bool
    message: str


class Forge(ABC):
    """Interface a forge adapter (github/gitlab/gitea) must implement."""

    @abstractmethod
    def list_renovate_prs(self, repo: Repo) -> list[PullRequest]:
        """Return open Renovate-labeled PRs for a single repo."""

    @abstractmethod
    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        """Attempt to merge a single PR, never raising on failure."""
