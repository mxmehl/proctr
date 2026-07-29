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

from proctr.forges.base import (
    ApproveResult,
    Forge,
    MergeResult,
    PullRequest,
    branch_matches_prefixes,
    resolve_filter_defaults,
)

if TYPE_CHECKING:
    from proctr.projects import Repo

LIST_FIELDS = (
    "createdAt,state,updatedAt,url,number,title,mergeable,mergeStateStatus,"
    "headRefName,reviewDecision"
)
GH_EXECUTABLE = shutil.which("gh") or "gh"
READY_MERGEABLE = "MERGEABLE"
READY_MERGE_STATE = "CLEAN"


class GitHubForge(Forge):
    """Lists and merges PRs matching configured label(s) and/or branch prefix(es) via the gh CLI."""

    def __init__(
        self,
        github_token: str | None,
        labels: list[str] | None = None,
        branch_prefixes: list[str] | None = None,
        match_mode: str = "and",
    ) -> None:
        """Initialize with an optional token and the label/branch-prefix filters."""
        self._github_token = github_token
        self._labels, self._branch_prefixes = resolve_filter_defaults(labels, branch_prefixes)
        self._match_mode = match_mode

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._github_token:
            env["GH_TOKEN"] = self._github_token
        return env

    def _fetch_prs(self, repo: Repo, *, use_label_filter: bool) -> list[dict]:
        """Run gh pr list, optionally pre-filtering server-side by label(s)."""
        label_flags = (
            [flag for label in self._labels for flag in ("--label", label)]
            if use_label_filter
            else []
        )
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
        return json.loads(result.stdout)

    def list_matching_prs(self, repo: Repo) -> list[PullRequest]:
        """Return open PRs matching the configured labels and/or branch prefixes.

        Labels are still filtered server-side via `--label` whenever
        possible (AND semantics, same as before). The one case that needs
        two queries is `match_mode == "or"` with both filters configured:
        a PR matching branch_prefixes alone (without the label) must be
        included too, so a second, unfiltered query is fetched and
        filtered client-side by branch prefix, then unioned with the
        label-filtered query (deduped by PR number).
        """
        labels_enabled = bool(self._labels)
        branch_enabled = bool(self._branch_prefixes)

        if labels_enabled and branch_enabled and self._match_mode == "or":
            label_matched = self._fetch_prs(repo, use_label_filter=True)
            all_prs = self._fetch_prs(repo, use_label_filter=False)
            branch_matched = [
                pr
                for pr in all_prs
                if branch_matches_prefixes(pr["headRefName"], self._branch_prefixes)
            ]
            combined = {pr["number"]: pr for pr in label_matched}
            combined.update({pr["number"]: pr for pr in branch_matched})
            raw_prs = list(combined.values())
        else:
            raw_prs = self._fetch_prs(repo, use_label_filter=labels_enabled)
            if branch_enabled:
                raw_prs = [
                    pr
                    for pr in raw_prs
                    if branch_matches_prefixes(pr["headRefName"], self._branch_prefixes)
                ]

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
                review_decision=pr["reviewDecision"],
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

    def approve_pr(self, pull_request: PullRequest) -> ApproveResult:
        """Approve a single PR via gh pr review --approve, never raising."""
        result = subprocess.run(  # noqa: S603
            [
                GH_EXECUTABLE,
                "pr",
                "review",
                str(pull_request.number),
                "-R",
                pull_request.repo.full_name,
                "--approve",
            ],
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        if result.returncode == 0:
            return ApproveResult(
                pull_request=pull_request, success=True, message=result.stdout.strip()
            )
        message = result.stderr.strip() or result.stdout.strip() or "gh pr review --approve failed"
        return ApproveResult(pull_request=pull_request, success=False, message=message)

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
