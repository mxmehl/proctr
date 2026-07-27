"""Tests for the GitHub forge adapter."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture
def pull_request() -> PullRequest:
    """A single PullRequest fixture matching FAKE_PR_JSON's first entry."""
    return PullRequest(
        repo=REPO,
        number=42,
        title="Update dependency foo to v2",
        url="https://github.com/mxmehl/my-tool/pull/42",
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 7, 2),
        mergeable="MERGEABLE",
        pipeline_status="CLEAN",
    )


def test_list_renovate_prs_builds_correct_command_and_parses_json() -> None:
    """Gh pr list is invoked with the right flags/token, and JSON output is parsed."""
    forge = GitHubForge(github_token="secret-token")
    fake_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        prs = forge.list_renovate_prs(REPO)

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert Path(cmd[0]).name == "gh"
    assert cmd[1:3] == ["pr", "list"]
    assert cmd[cmd.index("-R") + 1] == "mxmehl/my-tool"
    assert cmd[cmd.index("--label") + 1] == "Renovate"
    assert kwargs["env"]["GH_TOKEN"] == "secret-token"

    assert len(prs) == 1
    assert prs[0].number == 42
    assert prs[0].title == "Update dependency foo to v2"
    assert prs[0].mergeable == "MERGEABLE"


def test_list_prs_with_multiple_configured_labels() -> None:
    """Multiple configured labels produce one repeated --label flag per label."""
    forge = GitHubForge(github_token=None, labels=["Renovate", "dependencies"])
    fake_result = MagicMock(stdout=json.dumps([]))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        forge.list_renovate_prs(REPO)

    cmd = mock_run.call_args.args[0]
    label_positions = [i for i, arg in enumerate(cmd) if arg == "--label"]
    label_values = [cmd[i + 1] for i in label_positions]
    assert label_values == ["Renovate", "dependencies"]


def test_merge_pr_success(pull_request: PullRequest) -> None:
    """A successful gh pr merge invocation returns a successful MergeResult."""
    forge = GitHubForge(github_token=None)
    fake_ok = MagicMock(returncode=0, stdout="Merged\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        merge_result = forge.merge_pr(pull_request, method="squash")

    cmd = mock_run.call_args.args[0]
    assert Path(cmd[0]).name == "gh"
    assert cmd[1:3] == ["pr", "merge"]
    assert "--squash" in cmd
    assert merge_result.success is True


def test_merge_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing gh pr merge invocation returns a failed MergeResult, not an exception."""
    forge = GitHubForge(github_token=None)
    fake_fail = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    with patch("subprocess.run", return_value=fake_fail):
        merge_result = forge.merge_pr(pull_request, method="squash")

    assert merge_result.success is False
    assert "merge conflict" in merge_result.message


def test_checkout_pr_uses_force_flag_and_repo_cwd(pull_request: PullRequest) -> None:
    """Gh pr checkout is invoked with -f (force-reset stale branches) and cwd at the local repo."""
    forge = GitHubForge(github_token=None)
    fake_ok = MagicMock(returncode=0, stdout="Switched to branch\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        success, _message = forge.checkout_pr(pull_request)

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert Path(cmd[0]).name == "gh"
    assert cmd[1:3] == ["pr", "checkout"]
    assert cmd[3] == "42"
    assert "-f" in cmd
    assert kwargs["cwd"] == REPO.local_path
    assert success is True


def test_checkout_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing gh pr checkout invocation returns (False, message), not an exception."""
    forge = GitHubForge(github_token=None)
    fake_fail = MagicMock(returncode=1, stdout="", stderr="branch has diverged")

    with patch("subprocess.run", return_value=fake_fail):
        success, message = forge.checkout_pr(pull_request)

    assert success is False
    assert "diverged" in message
