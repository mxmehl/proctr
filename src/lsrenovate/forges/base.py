"""Forge-agnostic interface for listing and merging Renovate PRs.

Only GitHub is implemented today, but the interface is kept forge-agnostic
so gitlab (glab) and gitea (tea) adapters can be added later without
touching the app/UI layer.
"""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from lsrenovate.projects import Repo


@dataclass(frozen=True)
class PullRequest:
    """A single open Renovate pull request.

    `mergeable` is a raw, forge-specific conflict/approval status string.
    `pipeline_status` is the CI/pipeline outcome for the head commit (also
    forge-specific, e.g. "success"/"failed", or "N/A" if unavailable).
    Both are kept for display. `merge_ready` is the normalized signal used
    for coloring: True/False when the forge can tell us definitively, None
    when it can't (e.g. Gitea's `mergeable` flag is known to be unreliable
    upstream, so it never contributes a positive True there).
    """

    repo: Repo
    number: int
    title: str
    url: str
    created_at: datetime
    updated_at: datetime
    mergeable: str
    pipeline_status: str
    merge_ready: bool | None = None


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

    @abstractmethod
    def checkout_pr(self, pull_request: PullRequest) -> tuple[bool, str]:
        """Check out a PR's branch locally, force-resetting it to the current remote state.

        Renovate reuses branch names across unrelated updates, so a stale
        local branch from a previous PR run must never be trusted as-is.
        Returns (success, message); never raises.
        """
