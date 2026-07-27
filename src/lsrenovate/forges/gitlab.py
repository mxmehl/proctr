"""GitLab forge adapter backed by the `glab` CLI.

Supports multiple self-hosted instances: `glab` accepts per-invocation
auth via the GITLAB_TOKEN + GITLAB_HOST env vars, so no pre-login is
required (same approach as the GitHub adapter).
"""

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
GLAB_EXECUTABLE = shutil.which("glab") or "glab"
MERGEABLE = "MERGEABLE"
CONFLICTING = "CONFLICTING"
NO_PIPELINE = "N/A"
FAILED_PIPELINE_STATUSES = {"failed", "canceled", "skipped"}


class GitLabForge(Forge):
    """Lists and merges PRs matching configured label(s) via the glab CLI."""

    def __init__(
        self,
        host: str,
        token: str | None,
        labels: list[str] | None = None,
    ) -> None:
        """Initialize for a single GitLab host, with an optional token and labels."""
        self._host = host
        self._token = token
        self._labels = labels or list(DEFAULT_LABELS)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["GITLAB_HOST"] = self._host
        if self._token:
            env["GITLAB_TOKEN"] = self._token
        return env

    def list_renovate_prs(self, repo: Repo) -> list[PullRequest]:
        """Return open MRs matching all configured labels via glab mr list.

        `mergeable` reflects only whether GitLab sees a merge conflict
        (has_conflicts). Pipeline/CI outcome is a separate signal that
        `glab mr list` doesn't expose at all, so for each MR we do one
        follow-up `glab mr view` call to fetch the head pipeline status.
        """
        label_flags = [flag for label in self._labels for flag in ("--label", label)]
        result = subprocess.run(  # noqa: S603
            [
                GLAB_EXECUTABLE,
                "mr",
                "list",
                "-R",
                repo.full_name,
                *label_flags,
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            env=self._env(),
            check=True,
        )
        raw_mrs = json.loads(result.stdout)
        prs = []
        for mr in raw_mrs:
            pipeline_status = self._head_pipeline_status(repo, mr["iid"])
            prs.append(
                PullRequest(
                    repo=repo,
                    number=mr["iid"],
                    title=mr["title"],
                    url=mr["web_url"],
                    created_at=datetime.fromisoformat(mr["created_at"]),
                    updated_at=datetime.fromisoformat(mr["updated_at"]),
                    mergeable=CONFLICTING if mr["has_conflicts"] else MERGEABLE,
                    pipeline_status=pipeline_status or NO_PIPELINE,
                    merge_ready=not mr["has_conflicts"]
                    and pipeline_status not in FAILED_PIPELINE_STATUSES,
                )
            )
        return prs

    def _head_pipeline_status(self, repo: Repo, iid: int) -> str | None:
        """Fetch the head pipeline status for a single MR via glab mr view.

        Returns None if there's no pipeline at all (e.g. a repo without
        CI configured), which is treated as "not blocking" by merge_ready.
        """
        result = subprocess.run(  # noqa: S603
            [
                GLAB_EXECUTABLE,
                "mr",
                "view",
                str(iid),
                "-R",
                repo.full_name,
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            env=self._env(),
            check=True,
        )
        mr = json.loads(result.stdout)
        head_pipeline = mr.get("head_pipeline")
        return head_pipeline.get("status") if head_pipeline else None

    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        """Attempt to merge a single MR via glab mr merge, never raising."""
        method_flags = {
            "squash": ["--squash"],
            "rebase": ["--rebase"],
            "merge": [],
        }.get(method, [])
        result = subprocess.run(  # noqa: S603
            [
                GLAB_EXECUTABLE,
                "mr",
                "merge",
                str(pull_request.number),
                "-R",
                pull_request.repo.full_name,
                "--yes",
                *method_flags,
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
        message = result.stderr.strip() or result.stdout.strip() or "glab mr merge failed"
        return MergeResult(pull_request=pull_request, success=False, message=message)

    def checkout_pr(self, pull_request: PullRequest) -> tuple[bool, str]:
        """Check out an MR's branch via glab mr checkout -f, force-resetting any stale branch.

        -f resets the local branch to the MR's current remote state even
        if it has diverged (e.g. a reused Renovate branch name pointing at
        an unrelated older commit) — without it, glab refuses with an
        error rather than silently checking out stale content.
        """
        result = subprocess.run(  # noqa: S603
            [
                GLAB_EXECUTABLE,
                "mr",
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
        message = result.stderr.strip() or result.stdout.strip() or "glab mr checkout failed"
        return False, message
