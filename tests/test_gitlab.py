"""Tests for the GitLab forge adapter."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lsrenovate.forges.base import PullRequest
from lsrenovate.forges.gitlab import GitLabForge
from lsrenovate.projects import Repo

REPO = Repo(
    group="db",
    name="my-tool",
    forge="gitlab",
    url="https://gitlab.example.com/foss/my-tool",
    owner="foss",
    local_path=Path("~/Git/db/my-tool").expanduser(),
)

FAKE_MR_JSON = [
    {
        "iid": 42,
        "title": "Update dependency foo to v2",
        "web_url": "https://gitlab.example.com/foss/my-tool/-/merge_requests/42",
        "created_at": "2026-07-01T10:00:00.000Z",
        "updated_at": "2026-07-02T10:00:00.000Z",
        "has_conflicts": False,
    }
]


@pytest.fixture
def pull_request() -> PullRequest:
    """A single PullRequest fixture matching FAKE_MR_JSON's first entry."""
    return PullRequest(
        repo=REPO,
        number=42,
        title="Update dependency foo to v2",
        url="https://gitlab.example.com/foss/my-tool/-/merge_requests/42",
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 7, 2),
        mergeable="MERGEABLE",
        pipeline_status="success",
        merge_ready=True,
    )


def test_list_renovate_prs_builds_correct_command_and_parses_json() -> None:
    """Glab mr list is invoked with the right host/token/flags, and JSON is parsed."""
    forge = GitLabForge(host="gitlab.example.com", token="secret-token")
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": {"status": "success"}}))
    with patch("subprocess.run", side_effect=[list_result, view_result]) as mock_run:
        prs = forge.list_renovate_prs(REPO)

    args, kwargs = mock_run.call_args_list[0]
    cmd = args[0]
    assert Path(cmd[0]).name == "glab"
    assert cmd[1:3] == ["mr", "list"]
    assert cmd[cmd.index("-R") + 1] == "foss/my-tool"
    assert cmd[cmd.index("--label") + 1] == "Renovate"
    assert kwargs["env"]["GITLAB_TOKEN"] == "secret-token"
    assert kwargs["env"]["GITLAB_HOST"] == "gitlab.example.com"

    assert len(prs) == 1
    assert prs[0].number == 42
    assert prs[0].title == "Update dependency foo to v2"
    assert prs[0].mergeable == "MERGEABLE"
    assert prs[0].pipeline_status == "success"
    assert prs[0].merge_ready is True


def test_list_prs_not_ready_when_conflicting() -> None:
    """has_conflicts=True means merge_ready is False regardless of pipeline outcome.

    Pipeline status is still fetched and shown, since it's a useful signal
    on its own even for a conflicting MR.
    """
    forge = GitLabForge(host="gitlab.example.com", token=None)
    conflicting_mr = [{**FAKE_MR_JSON[0], "has_conflicts": True}]
    list_result = MagicMock(stdout=json.dumps(conflicting_mr))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": {"status": "success"}}))

    with patch("subprocess.run", side_effect=[list_result, view_result]):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].merge_ready is False
    assert prs[0].mergeable == "CONFLICTING"
    assert prs[0].pipeline_status == "success"


def test_list_prs_not_ready_when_pipeline_failed() -> None:
    """Regression test: no conflicts but a failed pipeline is not ready.

    GitLab's has_conflicts only reflects conflicts, not CI outcome, and
    `glab mr list` doesn't expose pipeline status at all — this mirrors a
    real MR that showed as mergeable despite a failed pipeline.
    """
    forge = GitLabForge(host="gitlab.example.com", token=None)
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": {"status": "failed"}}))

    with patch("subprocess.run", side_effect=[list_result, view_result]):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].mergeable == "MERGEABLE"  # no conflicts
    assert prs[0].pipeline_status == "failed"  # but the pipeline failed
    assert prs[0].merge_ready is False


def test_list_prs_ready_when_no_pipeline_exists() -> None:
    """A repo with no CI at all (head_pipeline is None) doesn't block merge_ready."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": None}))

    with patch("subprocess.run", side_effect=[list_result, view_result]):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].pipeline_status == "N/A"
    assert prs[0].merge_ready is True


def test_list_prs_with_multiple_configured_labels() -> None:
    """Multiple configured labels produce one repeated --label flag per label."""
    forge = GitLabForge(host="gitlab.example.com", token=None, labels=["Renovate", "dependencies"])
    fake_result = MagicMock(stdout=json.dumps([]))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        forge.list_renovate_prs(REPO)

    cmd = mock_run.call_args.args[0]
    label_positions = [i for i, arg in enumerate(cmd) if arg == "--label"]
    label_values = [cmd[i + 1] for i in label_positions]
    assert label_values == ["Renovate", "dependencies"]


def test_merge_pr_success_uses_squash_flag(pull_request: PullRequest) -> None:
    """merge_method='squash' translates to glab's --squash flag."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_ok = MagicMock(returncode=0, stdout="Merged\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        merge_result = forge.merge_pr(pull_request, method="squash")

    cmd = mock_run.call_args.args[0]
    assert Path(cmd[0]).name == "glab"
    assert cmd[1:3] == ["mr", "merge"]
    assert "--squash" in cmd
    assert merge_result.success is True


def test_merge_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing glab mr merge invocation returns a failed MergeResult, not an exception."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_fail = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    with patch("subprocess.run", return_value=fake_fail):
        merge_result = forge.merge_pr(pull_request, method="squash")

    assert merge_result.success is False
    assert "merge conflict" in merge_result.message
