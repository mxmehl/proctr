"""Minimal assert-based self-check for the GitHub forge adapter.

Run with: uv run python tests/test_task2.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from lsrenovate.forges.base import PullRequest
from lsrenovate.forges.github import GitHubForge
from lsrenovate.projects import Repo

REPO = Repo(
    group="github",
    name="my-tool",
    forge="github",
    url="https://github.com/mxmehl/my-tool",
    owner="mxmehl",
    local_path=Path("~/Git/github/my-tool").expanduser(),
)

FAKE_PR_JSON = [
    {
        "number": 42,
        "title": "Update dependency foo to v2",
        "url": "https://github.com/mxmehl/my-tool/pull/42",
        "createdAt": "2026-07-01T10:00:00Z",
        "updatedAt": "2026-07-02T10:00:00Z",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }
]


def test_list_renovate_prs_builds_correct_command_and_parses_json() -> None:
    forge = GitHubForge(github_token="secret-token")
    fake_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        prs = forge.list_renovate_prs(REPO)

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[:3] == ["gh", "pr", "list"]
    assert "-R" in cmd and cmd[cmd.index("-R") + 1] == "mxmehl/my-tool"
    assert "--label" in cmd and cmd[cmd.index("--label") + 1] == "Renovate"
    assert kwargs["env"]["GH_TOKEN"] == "secret-token"

    assert len(prs) == 1
    assert prs[0].number == 42
    assert prs[0].title == "Update dependency foo to v2"
    assert prs[0].mergeable == "MERGEABLE"


def test_list_prs_with_multiple_configured_labels() -> None:
    forge = GitHubForge(github_token=None, labels=["Renovate", "dependencies"])
    fake_result = MagicMock(stdout=json.dumps([]))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        forge.list_renovate_prs(REPO)

    cmd = mock_run.call_args.args[0]
    label_positions = [i for i, arg in enumerate(cmd) if arg == "--label"]
    assert len(label_positions) == 2, "expected one --label flag per configured label"
    label_values = [cmd[i + 1] for i in label_positions]
    assert label_values == ["Renovate", "dependencies"]


def test_merge_pr_success() -> None:
    forge = GitHubForge(github_token=None)
    pr = PullRequest(
        repo=REPO,
        number=42,
        title="Update dependency foo to v2",
        url="https://github.com/mxmehl/my-tool/pull/42",
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 7, 2),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
    )

    fake_ok = MagicMock(returncode=0, stdout="Merged\n", stderr="")
    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        merge_result = forge.merge_pr(pr, method="squash")
    args, _kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[:3] == ["gh", "pr", "merge"]
    assert "--squash" in cmd
    assert merge_result.success is True

    fake_fail = MagicMock(returncode=1, stdout="", stderr="merge conflict")
    with patch("subprocess.run", return_value=fake_fail):
        merge_result = forge.merge_pr(pr, method="squash")
    assert merge_result.success is False
    assert "merge conflict" in merge_result.message


if __name__ == "__main__":
    test_list_renovate_prs_builds_correct_command_and_parses_json()
    test_list_prs_with_multiple_configured_labels()
    test_merge_pr_success()
    print("All task 2 checks passed.")
