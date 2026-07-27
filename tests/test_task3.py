"""Minimal assert-based self-check for concurrent fetch aggregation.

Run with: uv run python tests/test_task3.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lsrenovate.fetch import fetch_all_prs
from lsrenovate.forges.base import Forge, MergeResult, PullRequest
from lsrenovate.projects import Repo


def _repo(name: str) -> Repo:
    return Repo(
        group="github",
        name=name,
        forge="github",
        url=f"https://github.com/mxmehl/{name}",
        owner="mxmehl",
        local_path=Path(f"~/Git/github/{name}").expanduser(),
    )


class FakeForge(Forge):
    """Returns canned PRs for known repos, raises for a designated failing repo."""

    def __init__(self, failing_repo_name: str) -> None:
        self._failing_repo_name = failing_repo_name

    def list_renovate_prs(self, repo: Repo) -> list[PullRequest]:
        if repo.name == self._failing_repo_name:
            raise RuntimeError("simulated gh failure")
        return [
            PullRequest(
                repo=repo,
                number=1,
                title=f"Update dep in {repo.name}",
                url=f"https://github.com/mxmehl/{repo.name}/pull/1",
                created_at=datetime(2026, 7, 1),
                updated_at=datetime(2026, 7, 1),
                mergeable="MERGEABLE",
                merge_state_status="CLEAN",
            )
        ]

    def merge_pr(self, pull_request: PullRequest, *, method: str) -> MergeResult:
        raise NotImplementedError


def test_fetch_all_prs_aggregates_and_isolates_failures() -> None:
    repos = [_repo("repo-a"), _repo("repo-b"), _repo("repo-c")]
    forge = FakeForge(failing_repo_name="repo-b")

    result = fetch_all_prs(repos, forge)

    assert len(result.pull_requests) == 2, (
        f"expected 2 successful PRs, got {len(result.pull_requests)}"
    )
    assert {pr.repo.name for pr in result.pull_requests} == {"repo-a", "repo-c"}

    assert len(result.errors) == 1, f"expected 1 error, got {len(result.errors)}"
    assert result.errors[0].repo.name == "repo-b"
    assert "simulated gh failure" in result.errors[0].error


if __name__ == "__main__":
    test_fetch_all_prs_aggregates_and_isolates_failures()
    print("All task 3 checks passed.")
