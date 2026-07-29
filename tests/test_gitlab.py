"""Tests for the GitLab forge adapter."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proctr.forges.base import PullRequest
from proctr.forges.gitlab import GitLabForge
from proctr.projects import Repo

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
        "source_branch": "renovate/foo-2.x",
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


def test_list_matching_prs_builds_correct_command_and_parses_json() -> None:
    """Glab mr list is invoked with the right host/token/flags, and JSON is parsed."""
    forge = GitLabForge(host="gitlab.example.com", token="secret-token")
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": {"status": "success"}}))
    with patch("subprocess.run", side_effect=[list_result, view_result]) as mock_run:
        prs = forge.list_matching_prs(REPO)

    args, kwargs = mock_run.call_args_list[0]
    cmd = args[0]
    assert Path(cmd[0]).name == "glab"
    assert cmd[1:3] == ["mr", "list"]
    assert cmd[cmd.index("-R") + 1] == "foss/my-tool"
    # with no labels/branch_prefixes configured, the default is branch-prefix
    # matching (renovate/) rather than a label, so no --label flag is sent
    assert "--label" not in cmd
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
        prs = forge.list_matching_prs(REPO)

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
        prs = forge.list_matching_prs(REPO)

    assert prs[0].mergeable == "MERGEABLE"  # no conflicts
    assert prs[0].pipeline_status == "failed"  # but the pipeline failed
    assert prs[0].merge_ready is False


def test_list_prs_ready_when_no_pipeline_exists() -> None:
    """A repo with no CI at all (head_pipeline is None) doesn't block merge_ready."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": None}))

    with patch("subprocess.run", side_effect=[list_result, view_result]):
        prs = forge.list_matching_prs(REPO)

    assert prs[0].pipeline_status == "N/A"
    assert prs[0].merge_ready is True


def test_list_prs_with_multiple_configured_labels() -> None:
    """Multiple configured labels produce one repeated --label flag per label."""
    forge = GitLabForge(host="gitlab.example.com", token=None, labels=["Renovate", "dependencies"])
    fake_result = MagicMock(stdout=json.dumps([]))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        forge.list_matching_prs(REPO)

    cmd = mock_run.call_args.args[0]
    label_positions = [i for i, arg in enumerate(cmd) if arg == "--label"]
    label_values = [cmd[i + 1] for i in label_positions]
    assert label_values == ["Renovate", "dependencies"]


def test_branch_prefix_only_mode_disables_label_flags() -> None:
    """With labels=[], no --label flags are sent and MRs are filtered by source branch only."""
    forge = GitLabForge(
        host="gitlab.example.com", token=None, labels=[], branch_prefixes=["renovate/"]
    )
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": None}))
    with patch("subprocess.run", side_effect=[list_result, view_result]) as mock_run:
        prs = forge.list_matching_prs(REPO)

    cmd = mock_run.call_args_list[0].args[0]
    assert "--label" not in cmd
    assert len(prs) == 1


def test_and_mode_narrows_label_filtered_results_by_branch_prefix() -> None:
    """match_mode='and' (default) does a single label-filtered query, then filters by branch."""
    forge = GitLabForge(
        host="gitlab.example.com",
        token=None,
        labels=["Renovate"],
        branch_prefixes=["dependabot/"],
        match_mode="and",
    )
    list_result = MagicMock(stdout=json.dumps(FAKE_MR_JSON))
    with patch("subprocess.run", return_value=list_result) as mock_run:
        prs = forge.list_matching_prs(REPO)

    assert mock_run.call_count == 1
    assert "--label" in mock_run.call_args_list[0].args[0]
    assert prs == []  # source_branch "renovate/foo-2.x" doesn't match "dependabot/"


def test_or_mode_unions_label_and_branch_matches_with_two_queries() -> None:
    """match_mode='or' with both filters runs two queries and unions/dedupes the results."""
    label_only_mr = {**FAKE_MR_JSON[0], "iid": 1, "source_branch": "some-other-branch"}
    branch_only_mr = {**FAKE_MR_JSON[0], "iid": 2, "source_branch": "renovate/bar-1.x"}
    in_both_mr = {**FAKE_MR_JSON[0], "iid": 3, "source_branch": "renovate/baz-1.x"}

    forge = GitLabForge(
        host="gitlab.example.com",
        token=None,
        labels=["Renovate"],
        branch_prefixes=["renovate/"],
        match_mode="or",
    )
    label_filtered_result = MagicMock(stdout=json.dumps([label_only_mr, in_both_mr]))
    unfiltered_result = MagicMock(stdout=json.dumps([label_only_mr, branch_only_mr, in_both_mr]))
    view_result = MagicMock(stdout=json.dumps({"head_pipeline": None}))

    with patch(
        "subprocess.run",
        side_effect=[
            label_filtered_result,
            unfiltered_result,
            view_result,
            view_result,
            view_result,
        ],
    ) as mock_run:
        prs = forge.list_matching_prs(REPO)

    assert mock_run.call_count == 5
    assert "--label" in mock_run.call_args_list[0].args[0]
    assert "--label" not in mock_run.call_args_list[1].args[0]
    assert {pr.number for pr in prs} == {1, 2, 3}


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


def test_approve_pr_success(pull_request: PullRequest) -> None:
    """A successful glab mr approve invocation returns a successful ApproveResult."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_ok = MagicMock(returncode=0, stdout="Approved\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        approve_result = forge.approve_pr(pull_request)

    cmd = mock_run.call_args.args[0]
    assert Path(cmd[0]).name == "glab"
    assert cmd[1:3] == ["mr", "approve"]
    assert cmd[3] == "42"
    assert approve_result.success is True


def test_approve_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing glab mr approve invocation returns a failed ApproveResult, not raise."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_fail = MagicMock(returncode=1, stdout="", stderr="not allowed to approve")

    with patch("subprocess.run", return_value=fake_fail):
        approve_result = forge.approve_pr(pull_request)

    assert approve_result.success is False
    assert "not allowed" in approve_result.message


def test_checkout_pr_uses_force_flag_and_repo_cwd(pull_request: PullRequest) -> None:
    """Glab mr checkout is invoked with -f and cwd at the local repo."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_ok = MagicMock(returncode=0, stdout="Switched to branch\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        success, _message = forge.checkout_pr(pull_request)

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert Path(cmd[0]).name == "glab"
    assert cmd[1:3] == ["mr", "checkout"]
    assert cmd[3] == "42"
    assert "-f" in cmd
    assert kwargs["cwd"] == REPO.local_path
    assert success is True


def test_checkout_pr_failure_on_divergence_does_not_raise(pull_request: PullRequest) -> None:
    """Glab refuses on a diverged local branch; the failure is reported, not raised."""
    forge = GitLabForge(host="gitlab.example.com", token=None)
    fake_fail = MagicMock(returncode=1, stdout="", stderr="Local branch has diverged")

    with patch("subprocess.run", return_value=fake_fail):
        success, message = forge.checkout_pr(pull_request)

    assert success is False
    assert "diverged" in message
