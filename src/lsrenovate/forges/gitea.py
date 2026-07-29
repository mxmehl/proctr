"""Gitea forge adapter backed by the `tea` CLI.

lsrenovate never handles Gitea tokens: `tea` has no per-invocation
token/host env var mechanism, only pre-registered named logins
(`tea login add --name=X --url=Y --token=Z`), selected here via
`--login <name>`. Users must register each Gitea instance themselves;
see the README for details.

`tea pulls list` has no server-side label filter, so labels are matched
client-side against the comma-separated `labels` field (AND semantics,
matching the other forge adapters' repeated-label behavior).

Gitea's `mergeable` field is documented upstream as sometimes wrong
(Gitea issue #19755: it can report false for a PR that's actually
mergeable). It's still used to compute merge_ready, though: a merge
attempt (`tea pulls merge`) never raises and reports failure cleanly if
there really is a conflict, so a wrong "mergeable" signal only costs one
failed merge attempt with a clear error, not a silently bad merge — the
asymmetric risk that justifies distrusting a forge's signal (as with
GitLab's pipeline status) doesn't apply here. Pipeline/CI status is
fetched separately via `tea api .../commits/{ref}/status` (the combined
commit status endpoint) and also feeds into merge_ready.

`review_decision` (unlike GitHub, which exposes it as one field) is
derived from two extra API calls: the repo's branch protection rules
(for the required-approval count on the PR's base branch, fetched once
per repo) and each PR's reviews (fetched once per PR). Only official,
non-dismissed, non-stale reviews count, mirroring what Gitea itself uses
to decide mergeability.
"""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from lsrenovate.forges.base import (
    ApproveResult,
    Forge,
    MergeResult,
    PullRequest,
    branch_matches_prefixes,
    combine_match,
    resolve_filter_defaults,
)

if TYPE_CHECKING:
    from lsrenovate.projects import Repo

TEA_EXECUTABLE = shutil.which("tea") or "tea"
GIT_EXECUTABLE = shutil.which("git") or "git"
LIST_FIELDS = "index,title,url,created,updated,labels,mergeable,head,base"
MERGE_STYLES = {"squash", "merge", "rebase", "rebase-merge"}
NO_PIPELINE = "N/A"
FAILED_COMBINED_STATUSES = {"error", "failure"}
REVIEW_REQUEST_CHANGES = "REQUEST_CHANGES"
REVIEW_APPROVED = "APPROVED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"


class GiteaForge(Forge):
    """Lists and merges PRs matching configured label(s) and/or branch prefix(es) via tea."""

    def __init__(
        self,
        login: str,
        labels: list[str] | None = None,
        branch_prefixes: list[str] | None = None,
        match_mode: str = "and",
    ) -> None:
        """Initialize with a pre-registered tea login name and the label/branch-prefix filters."""
        self._login = login
        self._labels, self._branch_prefixes = resolve_filter_defaults(labels, branch_prefixes)
        self._match_mode = match_mode

    def list_renovate_prs(self, repo: Repo) -> list[PullRequest]:
        """Return open PRs matching the configured labels and/or branch prefixes.

        Neither filter has server-side support in `tea pulls list`, so all
        open PRs are fetched and both are matched client-side (labels
        against the comma-separated `labels` field, branch prefix against
        the `head` field), combined per `match_mode`.
        """
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "pulls",
                "list",
                "--repo",
                repo.full_name,
                "--login",
                self._login,
                "--fields",
                LIST_FIELDS,
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        raw_prs = json.loads(result.stdout)
        labels_enabled = bool(self._labels)
        branch_enabled = bool(self._branch_prefixes)
        required_approvals = self._required_approvals(repo)
        prs = []
        for pr in raw_prs:
            matched = combine_match(
                label_match=self._has_all_labels(pr.get("labels", "")),
                branch_match=branch_matches_prefixes(pr["head"], self._branch_prefixes),
                labels_enabled=labels_enabled,
                branch_enabled=branch_enabled,
                match_mode=self._match_mode,
            )
            if not matched:
                continue
            combined_status = self._combined_status(repo, pr["head"])
            mergeable = pr["mergeable"]
            prs.append(
                PullRequest(
                    repo=repo,
                    number=int(pr["index"]),
                    title=pr["title"],
                    url=pr["url"],
                    created_at=datetime.fromisoformat(pr["created"]),
                    updated_at=datetime.fromisoformat(pr["updated"]),
                    mergeable=mergeable,
                    pipeline_status=combined_status or NO_PIPELINE,
                    merge_ready=mergeable == "true"
                    and combined_status not in FAILED_COMBINED_STATUSES,
                    review_decision=self._review_decision(
                        repo, int(pr["index"]), pr["base"], required_approvals
                    ),
                )
            )
        return prs

    def _has_all_labels(self, labels_field: str) -> bool:
        pr_labels = {label.strip() for label in labels_field.split(",") if label.strip()}
        return all(label in pr_labels for label in self._labels)

    def _required_approvals(self, repo: Repo) -> dict[str, int]:
        """Fetch each protected branch's required-approval count via the Gitea API.

        Returns {} on any failure (e.g. no permission to view protection
        rules), which `_review_decision` treats as "no review requirement
        configured" — the same tolerance already applied to Gitea's
        `mergeable` field: a wrong/missing signal here only affects a
        display column, never gates an actual merge attempt.
        """
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "api",
                f"/repos/{repo.full_name}/branch_protections",
                "--repo",
                repo.full_name,
                "--login",
                self._login,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return {}
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}
        # ponytail: exact branch_name match only. Gitea allows glob patterns
        # (e.g. "release/*") in a protection rule's branch_name, not handled
        # here — upgrade path is fnmatch against the PR's base branch if a
        # real repo ever needs it.
        return {rule["branch_name"]: rule.get("required_approvals", 0) for rule in data}

    def _review_decision(
        self, repo: Repo, index: int, base_branch: str, required_approvals: dict[str, int]
    ) -> str:
        """Compute a GitHub-reviewDecision-shaped string from reviews + branch protection.

        Gitea has no single reviewDecision field, so this combines the PR's
        reviews (state per reviewer) with the repo's required-approval
        count for the PR's base branch. Only official, non-dismissed,
        non-stale reviews count — the same fields Gitea itself uses to
        decide mergeability. An unprotected branch with at least one
        approval still reports "APPROVED" (an actual approval is a more
        useful signal than a blank cell); only a branch with neither a
        required-approval rule nor any approval reports "".
        """
        active_reviews = [
            review
            for review in self._reviews(repo, index)
            if review.get("official") and not review.get("dismissed") and not review.get("stale")
        ]
        if any(review.get("state") == REVIEW_REQUEST_CHANGES for review in active_reviews):
            return REVIEW_CHANGES_REQUESTED
        approved_count = sum(
            1 for review in active_reviews if review.get("state") == REVIEW_APPROVED
        )
        required = required_approvals.get(base_branch, 0)
        if required > 0:
            return REVIEW_APPROVED if approved_count >= required else REVIEW_REQUIRED
        return REVIEW_APPROVED if approved_count > 0 else ""

    def _reviews(self, repo: Repo, index: int) -> list[dict]:
        """Fetch a PR's reviews via the Gitea API. Returns [] on any failure, never raises."""
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "api",
                f"/repos/{repo.full_name}/pulls/{index}/reviews",
                "--repo",
                repo.full_name,
                "--login",
                self._login,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def _combined_status(self, repo: Repo, ref: str) -> str | None:
        """Fetch the combined commit status for a PR's head ref via the Gitea API.

        Returns None if there's no status at all (e.g. a repo without CI
        configured), which is treated as "not blocking" by merge_ready.
        """
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "api",
                f"/repos/{repo.full_name}/commits/{ref}/status",
                "--repo",
                repo.full_name,
                "--login",
                self._login,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return data.get("state")

    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        """Attempt to merge a single PR via tea pulls merge, never raising."""
        style = method if method in MERGE_STYLES else "merge"
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "pulls",
                "merge",
                str(pull_request.number),
                "--repo",
                pull_request.repo.full_name,
                "--login",
                self._login,
                "--style",
                style,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return MergeResult(
                pull_request=pull_request, success=True, message=result.stdout.strip()
            )
        message = result.stderr.strip() or result.stdout.strip() or "tea pulls merge failed"
        return MergeResult(pull_request=pull_request, success=False, message=message)

    def approve_pr(self, pull_request: PullRequest) -> ApproveResult:
        """Approve a single PR via tea pulls approve, never raising."""
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "pulls",
                "approve",
                str(pull_request.number),
                "--repo",
                pull_request.repo.full_name,
                "--login",
                self._login,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return ApproveResult(
                pull_request=pull_request, success=True, message=result.stdout.strip()
            )
        message = result.stderr.strip() or result.stdout.strip() or "tea pulls approve failed"
        return ApproveResult(pull_request=pull_request, success=False, message=message)

    def checkout_pr(self, pull_request: PullRequest) -> tuple[bool, str]:
        """Check out a PR's branch, force-resetting it to the current remote state.

        `tea pulls checkout` fetches the PR's head ref and checks it out
        detached, deliberately bypassing any stale local branch of the
        same name rather than trusting it — safe, but not push-ready. A
        follow-up `git checkout -B <branch> origin/<branch>` puts you on a
        real local branch reset to that same fresh commit, matching the
        end state of the GitHub/GitLab checkout actions.
        """
        head_branch = self._head_branch(pull_request.repo, pull_request.number)
        if head_branch is None:
            return False, f"Could not resolve head branch for PR #{pull_request.number}"

        checkout_result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "pulls",
                "checkout",
                str(pull_request.number),
                "--repo",
                pull_request.repo.full_name,
                "--login",
                self._login,
            ],
            cwd=pull_request.repo.local_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout_result.returncode != 0:
            message = (
                checkout_result.stderr.strip()
                or checkout_result.stdout.strip()
                or "tea pulls checkout failed"
            )
            return False, message

        branch_result = subprocess.run(  # noqa: S603
            [GIT_EXECUTABLE, "checkout", "-B", head_branch, f"origin/{head_branch}"],
            cwd=pull_request.repo.local_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if branch_result.returncode == 0:
            return True, branch_result.stderr.strip() or branch_result.stdout.strip()
        message = (
            branch_result.stderr.strip() or branch_result.stdout.strip() or "git checkout -B failed"
        )
        return False, message

    def _head_branch(self, repo: Repo, index: int) -> str | None:
        """Resolve the head branch name for a single PR via tea pulls list."""
        result = subprocess.run(  # noqa: S603
            [
                TEA_EXECUTABLE,
                "pulls",
                "list",
                "--repo",
                repo.full_name,
                "--login",
                self._login,
                "--fields",
                "index,head",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        pr = next((p for p in data if int(p["index"]) == index), None)
        return pr["head"] if pr else None
