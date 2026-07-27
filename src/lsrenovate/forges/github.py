"""GitHub forge adapter backed by the `gh` CLI."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime

from lsrenovate.forges.base import Forge, MergeResult, PullRequest
from lsrenovate.projects import Repo

DEFAULT_LABELS = ("Renovate",)
LIST_FIELDS = "createdAt,state,updatedAt,url,number,title,mergeable,mergeStateStatus"


class GitHubForge(Forge):
    """Lists and merges PRs matching configured label(s) via the gh CLI."""

    def __init__(self, github_token: str | None, labels: list[str] | None = None) -> None:
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
                "gh",
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
                merge_state_status=pr["mergeStateStatus"],
            )
            for pr in raw_prs
        ]

    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        """Attempt to merge a single PR via gh pr merge, never raising."""
        result = subprocess.run(  # noqa: S603
            [
                "gh",
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
