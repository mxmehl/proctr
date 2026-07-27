"""Tests for the merge summary builder."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from datetime import datetime
from pathlib import Path

from lsrenovate.app import _mergeable_cell, _pipeline_cell, build_merge_summary
from lsrenovate.forges.base import MergeResult, PullRequest
from lsrenovate.projects import Repo

REPO = Repo(
    group="github",
    name="my-tool",
    forge="github",
    url="https://github.com/mxmehl/my-tool",
    owner="mxmehl",
    local_path=Path("~/Git/github/my-tool").expanduser(),
)


def _pr(number: int) -> PullRequest:
    return PullRequest(
        repo=REPO,
        number=number,
        title=f"Update dep #{number}",
        url=f"https://github.com/mxmehl/my-tool/pull/{number}",
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 7, 2),
        mergeable="MERGEABLE",
        pipeline_status="CLEAN",
    )


def test_build_merge_summary_all_success() -> None:
    """An all-success batch reports N/N merged with no failure lines."""
    results = [
        MergeResult(pull_request=_pr(1), success=True, message="Merged"),
        MergeResult(pull_request=_pr(2), success=True, message="Merged"),
    ]
    summary = build_merge_summary(results)
    assert "Merged 2/2 PR(s)." in summary
    assert "FAILED" not in summary


def test_build_merge_summary_mixed_results() -> None:
    """A mixed batch reports the correct ratio and one FAILED line per failure."""
    results = [
        MergeResult(pull_request=_pr(1), success=True, message="Merged"),
        MergeResult(pull_request=_pr(2), success=False, message="merge conflict"),
        MergeResult(pull_request=_pr(3), success=False, message="not mergeable"),
    ]
    summary = build_merge_summary(results)
    assert "Merged 1/3 PR(s)." in summary
    assert "FAILED mxmehl/my-tool#2: merge conflict" in summary
    assert "FAILED mxmehl/my-tool#3: not mergeable" in summary


def test_build_merge_summary_all_failed() -> None:
    """An all-failed batch reports 0/N merged with the failure reason."""
    results = [MergeResult(pull_request=_pr(1), success=False, message="already merged")]
    summary = build_merge_summary(results)
    assert "Merged 0/1 PR(s)." in summary
    assert "FAILED mxmehl/my-tool#1: already merged" in summary


def test_pipeline_cell_green_for_success_across_forges() -> None:
    """GitHub's CLEAN and GitLab/Gitea's success both render green."""
    for value in ("CLEAN", "success"):
        assert str(_pipeline_cell(value).style) == "bold green"


def test_pipeline_cell_red_for_failure_across_forges() -> None:
    """Every forge's failing status value renders red, independent of merge_ready."""
    for value in ("UNSTABLE", "failed", "canceled", "skipped", "error", "failure"):
        assert str(_pipeline_cell(value).style) == "bold red"


def test_mergeable_cell_green_for_mergeable_across_forges() -> None:
    """GitHub/GitLab's MERGEABLE and Gitea's 'true' both render green."""
    for value in ("MERGEABLE", "true"):
        assert str(_mergeable_cell(value).style) == "bold green"


def test_mergeable_cell_red_for_conflicting_across_forges() -> None:
    """GitHub/GitLab's CONFLICTING and Gitea's 'false' both render red."""
    for value in ("CONFLICTING", "false"):
        assert str(_mergeable_cell(value).style) == "bold red"


def test_mergeable_cell_independent_of_pipeline_status() -> None:
    """Regression test: a failing pipeline must not paint an otherwise-mergeable PR red.

    Mergeable and Pipeline are independent signals — this was the exact
    bug that started the column redesign (a GitLab MR silently shown as
    mergeable despite a failed pipeline) and it resurfaced in reverse:
    GitHub's merge_ready (which factors in mergeStateStatus) used to gate
    this cell's color, so an UNSTABLE pipeline wrongly painted a genuinely
    conflict-free "MERGEABLE" PR red.
    """
    assert str(_mergeable_cell("MERGEABLE").style) == "bold green"
    assert str(_pipeline_cell("UNSTABLE").style) == "bold red"


def test_pipeline_cell_plain_for_unknown_or_no_pipeline() -> None:
    """Statuses that are neither a known success nor failure stay uncolored."""
    for value in ("N/A", "running", "pending", "BLOCKED"):
        assert str(_pipeline_cell(value).style) == ""
