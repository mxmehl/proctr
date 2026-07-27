"""GitHub forge adapter backed by the `gh` CLI."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from lsrenovate.forges.base import Forge, MergeResult, PullRequest

if TYPE_CHECKING:
    from lsrenovate.projects import Repo

DEFAULT_LABELS = ("Renovate",)
LIST_FIELDS = "createdAt,state,updatedAt,url,number,title,mergeable,mergeStateStatus"
GH_EXECUTABLE = shutil.which("gh") or "gh"
READY_MERGEABLE = "MERGEABLE"
READY_MERGE_STATE = "CLEAN"


class GitHubForge(Forge):
    """Lists and merges PRs matching configured label(s) via the gh CLI."""

    def __init__(self, github_token: str | None, labels: list[str] | None = None) -> None:
        """Initialize with an optional token and label filter (defaults to DEFAULT_LABELS)."""
        self._github_token = github_token
        self._labels = labels or list(DEFAULT_LABELS)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._github_token:
            env["GH_TOKEN"] = self._github_token
        return env

    def list_renovate_prs(self, repo: Repo) -> list[PullRequest]:
        """Return open PRs matching all configured labels via gh pr list."""
        label_flags = [flag for label in self._labels for flag in ("--label", label)]
        result = subprocess.run(  # noqa: S603
            [
                GH_EXECUTABLE,
                "pr",
                "list",
                "-R",
                repo.full_name,
                *label_flags,
                "--json",
                LIST_FIELDS,
            ],
            capture_output=True,
            text=True,
            env=self._env(),
            check=True,
        )
        raw_prs = json.loads(result.stdout)
        return [
            PullRequest(
                repo=repo,
                number=pr["number"],
                title=pr["title"],
                url=pr["url"],
                created_at=datetime.fromisoformat(pr["createdAt"]),
                updated_at=datetime.fromisoformat(pr["updatedAt"]),
                mergeable=pr["mergeable"],
                pipeline_status=pr["mergeStateStatus"],
                merge_ready=(
                    pr["mergeable"] == READY_MERGEABLE
                    and pr["mergeStateStatus"] == READY_MERGE_STATE
                ),
            )
            for pr in raw_prs
        ]

    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        """Attempt to merge a single PR via gh pr merge, never raising."""
        result = subprocess.run(  # noqa: S603
            [
                GH_EXECUTABLE,
                "pr",
                "merge",
                str(pull_request.number),
                "-R",
                pull_request.repo.full_name,
                f"--{method}",
            ],
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        if result.returncode == 0:
            return MergeResult(
                pull_request=pull_request, success=True, message=result.stdout.strip()
            )
        message = result.stderr.strip() or result.stdout.strip() or "gh pr merge failed"
        return MergeResult(pull_request=pull_request, success=False, message=message)

    def checkout_pr(self, pull_request: PullRequest) -> tuple[bool, str]:
        """Check out a PR's branch via gh pr checkout -f, force-resetting any stale branch.

        -f resets the local branch to the PR's current remote state even
        if it has diverged (e.g. a reused Renovate branch name pointing at
        an unrelated older commit) — without it, gh silently leaves a
        stale local branch untouched instead of erroring.
        """
        result = subprocess.run(  # noqa: S603
            [
                GH_EXECUTABLE,
                "pr",
                "checkout",
                str(pull_request.number),
                "-R",
                pull_request.repo.full_name,
                "-f",
            ],
            cwd=pull_request.repo.local_path,
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        if result.returncode == 0:
            return True, result.stderr.strip() or result.stdout.strip()
        message = result.stderr.strip() or result.stdout.strip() or "gh pr checkout failed"
        return False, message
