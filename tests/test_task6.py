"""Minimal assert-based self-check for merge summary building.

Run with: uv run python tests/test_task6.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lsrenovate.app import build_merge_summary
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
        merge_state_status="CLEAN",
    )


def test_build_merge_summary_all_success() -> None:
    results = [
        MergeResult(pull_request=_pr(1), success=True, message="Merged"),
        MergeResult(pull_request=_pr(2), success=True, message="Merged"),
    ]
    summary = build_merge_summary(results)
    assert "Merged 2/2 PR(s)." in summary
    assert "FAILED" not in summary


def test_build_merge_summary_mixed_results() -> None:
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
    results = [MergeResult(pull_request=_pr(1), success=False, message="already merged")]
    summary = build_merge_summary(results)
    assert "Merged 0/1 PR(s)." in summary
    assert "FAILED mxmehl/my-tool#1: already merged" in summary


if __name__ == "__main__":
    test_build_merge_summary_all_success()
    test_build_merge_summary_mixed_results()
    test_build_merge_summary_all_failed()
    print("All task 6 checks passed.")
