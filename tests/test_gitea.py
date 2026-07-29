"""Tests for the Gitea forge adapter."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lsrenovate.forges.base import PullRequest
from lsrenovate.forges.gitea import GiteaForge
from lsrenovate.projects import Repo

REPO = Repo(
    group="src.mehl.mx",
    name="vpn-server",
    forge="gitea",
    url="https://git.fsfe.org/fsfe-system-hackers/vpn-server",
    owner="fsfe-system-hackers",
    local_path=Path("~/Git/src.mehl.mx/vpn-server").expanduser(),
)

# Real shape captured live from `tea pr list -o json --fields
# index,title,state,author,updated,labels,mergeable` against git.fsfe.org.
FAKE_PR_JSON = [
    {
        "index": "427",
        "title": "Update postgres Docker tag to v18",
        "url": "https://git.fsfe.org/fsfe-system-hackers/vpn-server/pulls/427",
        "created": "2026-02-20T00:11:04Z",
        "updated": "2026-02-28T00:11:04Z",
        "labels": "maintenance,Renovate",
        "mergeable": "false",
        "head": "renovate/postgres-18.x",
        "base": "main",
    },
    {
        "index": "285",
        "title": "handle quoted selectors",
        "url": "https://git.fsfe.org/fsfe-system-hackers/vpn-server/pulls/285",
        "created": "2024-01-10T18:31:19Z",
        "updated": "2024-01-15T18:31:19Z",
        "labels": "",
        "mergeable": "false",
        "head": "quoted-selectors",
        "base": "main",
    },
]

FAKE_STATUS_JSON = {"state": "success"}
# No branch protection configured by default, so review_decision resolves to ""
# without needing a reviews call for most tests (required_approvals=0 short-circuits
# _review_decision only after checking for REQUEST_CHANGES, so an empty reviews list
# is still fetched once per matched PR).
FAKE_NO_BRANCH_PROTECTIONS_JSON: list = []
FAKE_NO_REVIEWS_JSON: list = []


@pytest.fixture
def pull_request() -> PullRequest:
    """A single PullRequest fixture matching FAKE_PR_JSON's first (labeled) entry."""
    return PullRequest(
        repo=REPO,
        number=427,
        title="Update postgres Docker tag to v18",
        url="https://git.fsfe.org/fsfe-system-hackers/vpn-server/pulls/427",
        created_at=datetime(2026, 2, 20),
        updated_at=datetime(2026, 2, 28),
        mergeable="false",
        pipeline_status="success",
        merge_ready=None,
    )


def test_list_renovate_prs_builds_correct_command_and_parses_json() -> None:
    """Tea pulls list is invoked with --repo/--login/--fields, and JSON is parsed."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(
        returncode=0, stdout=json.dumps([{"branch_name": "main", "required_approvals": 1}])
    )
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [{"state": "APPROVED", "official": True, "dismissed": False, "stale": False}]
        ),
    )
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ) as mock_run:
        prs = forge.list_renovate_prs(REPO)

    cmd = mock_run.call_args_list[0].args[0]
    assert Path(cmd[0]).name == "tea"
    assert cmd[1:3] == ["pulls", "list"]
    assert cmd[cmd.index("--repo") + 1] == "fsfe-system-hackers/vpn-server"
    assert cmd[cmd.index("--login") + 1] == "git.fsfe.org"

    # with no labels/branch_prefixes configured, the default is branch-prefix
    # matching (renovate/), so only the PR with a matching head branch survives
    assert len(prs) == 1
    assert prs[0].number == 427
    assert prs[0].mergeable == "false"
    assert prs[0].pipeline_status == "success"
    assert prs[0].merge_ready is False  # mergeable=false is trusted as a real conflict signal
    assert prs[0].review_decision == "APPROVED"

    protections_cmd = mock_run.call_args_list[1].args[0]
    assert protections_cmd[1] == "api"
    assert protections_cmd[2] == "/repos/fsfe-system-hackers/vpn-server/branch_protections"

    status_cmd = mock_run.call_args_list[2].args[0]
    assert status_cmd[1] == "api"
    assert (
        status_cmd[2]
        == "/repos/fsfe-system-hackers/vpn-server/commits/renovate/postgres-18.x/status"
    )

    reviews_cmd = mock_run.call_args_list[3].args[0]
    assert reviews_cmd[1] == "api"
    assert reviews_cmd[2] == "/repos/fsfe-system-hackers/vpn-server/pulls/427/reviews"


def test_merge_ready_is_true_when_mergeable_and_pipeline_passing() -> None:
    """mergeable=true and a passing pipeline together mean merge_ready is True.

    A wrong "mergeable" signal from Gitea only costs one failed merge
    attempt (tea pulls merge fails cleanly on a real conflict), not a
    silently bad merge, so it's safe to trust it here.
    """
    forge = GiteaForge(login="git.fsfe.org")
    mergeable_pr = [{**FAKE_PR_JSON[0], "mergeable": "true"}]
    list_result = MagicMock(stdout=json.dumps(mergeable_pr))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].merge_ready is True


def test_merge_ready_is_false_when_not_mergeable() -> None:
    """mergeable=false is not ready, even with a passing pipeline."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].merge_ready is False


def test_merge_ready_is_false_when_pipeline_failed() -> None:
    """A failing combined status is not ready, even if mergeable=true."""
    forge = GiteaForge(login="git.fsfe.org")
    mergeable_pr = [{**FAKE_PR_JSON[0], "mergeable": "true"}]
    list_result = MagicMock(stdout=json.dumps(mergeable_pr))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps({"state": "failure"}))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].pipeline_status == "failure"
    assert prs[0].merge_ready is False


def test_review_decision_approved_when_enough_official_approvals() -> None:
    """A required_approvals count met by official, non-dismissed reviews yields APPROVED."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(
        returncode=0, stdout=json.dumps([{"branch_name": "main", "required_approvals": 1}])
    )
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [{"state": "APPROVED", "official": True, "dismissed": False, "stale": False}]
        ),
    )
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == "APPROVED"


def test_review_decision_review_required_when_not_enough_approvals() -> None:
    """A required_approvals count not yet met by approvals yields REVIEW_REQUIRED."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(
        returncode=0, stdout=json.dumps([{"branch_name": "main", "required_approvals": 1}])
    )
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == "REVIEW_REQUIRED"


def test_review_decision_changes_requested_overrides_approval_count() -> None:
    """An active official REQUEST_CHANGES review wins over an unmet or met approval count."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(
        returncode=0, stdout=json.dumps([{"branch_name": "main", "required_approvals": 1}])
    )
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [{"state": "REQUEST_CHANGES", "official": True, "dismissed": False, "stale": False}]
        ),
    )
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == "CHANGES_REQUESTED"


def test_review_decision_ignores_dismissed_and_stale_reviews() -> None:
    """Dismissed or stale reviews don't count toward REQUEST_CHANGES or approval totals."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(
        returncode=0, stdout=json.dumps([{"branch_name": "main", "required_approvals": 1}])
    )
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {"state": "REQUEST_CHANGES", "official": True, "dismissed": True, "stale": False},
                {"state": "APPROVED", "official": True, "dismissed": False, "stale": True},
            ]
        ),
    )
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == "REVIEW_REQUIRED"


def test_review_decision_empty_when_no_branch_protection() -> None:
    """No required-approval rule for the PR's base branch yields an empty review_decision."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == ""


def test_review_decision_approved_when_no_branch_protection_but_has_approval() -> None:
    """An approval still reports APPROVED even without a required-approval rule."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [{"state": "APPROVED", "official": True, "dismissed": False, "stale": False}]
        ),
    )
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == "APPROVED"


def test_review_decision_falls_back_to_empty_on_api_failures() -> None:
    """A failing branch_protections or reviews API call is treated as no requirement, not raised."""
    forge = GiteaForge(login="git.fsfe.org")
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=1, stdout="", stderr="permission denied")
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=1, stdout="", stderr="permission denied")
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert prs[0].review_decision == ""


def test_label_filtering_requires_all_configured_labels() -> None:
    """A PR must carry all configured labels (AND semantics), not just one."""
    forge = GiteaForge(login="git.fsfe.org", labels=["Renovate", "maintenance"])
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert len(prs) == 1
    assert prs[0].number == 427


def test_no_labels_configured_or_matching_returns_empty() -> None:
    """A label with no matching PR returns an empty list, not an error."""
    forge = GiteaForge(login="git.fsfe.org", labels=["nonexistent-label"])
    fake_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    with patch("subprocess.run", return_value=fake_result):
        prs = forge.list_renovate_prs(REPO)

    assert prs == []


def test_branch_prefix_only_mode_matches_by_head_field() -> None:
    """With labels=[], PRs are matched solely by the head branch field's prefix."""
    forge = GiteaForge(login="git.fsfe.org", labels=[], branch_prefixes=["renovate/"])
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[list_result, protections_result, status_result, reviews_result],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert [pr.number for pr in prs] == [427]


def test_and_mode_requires_both_label_and_branch_prefix() -> None:
    """match_mode='and' (default) excludes a PR that only matches one of the two filters."""
    forge = GiteaForge(
        login="git.fsfe.org",
        labels=["Renovate"],
        branch_prefixes=["quoted-selectors"],
        match_mode="and",
    )
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    with patch("subprocess.run", return_value=list_result):
        prs = forge.list_renovate_prs(REPO)

    # PR 427 has the label but not the branch prefix; PR 285 has the branch prefix but not
    # the label - neither satisfies both, so both are excluded.
    assert prs == []


def test_or_mode_matches_either_label_or_branch_prefix() -> None:
    """match_mode='or' includes a PR that matches only one of the two filters."""
    forge = GiteaForge(
        login="git.fsfe.org",
        labels=["Renovate"],
        branch_prefixes=["quoted-selectors"],
        match_mode="or",
    )
    list_result = MagicMock(stdout=json.dumps(FAKE_PR_JSON))
    protections_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_BRANCH_PROTECTIONS_JSON))
    status_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_STATUS_JSON))
    reviews_result = MagicMock(returncode=0, stdout=json.dumps(FAKE_NO_REVIEWS_JSON))
    with patch(
        "subprocess.run",
        side_effect=[
            list_result,
            protections_result,
            status_result,
            reviews_result,
            status_result,
            reviews_result,
        ],
    ):
        prs = forge.list_renovate_prs(REPO)

    assert {pr.number for pr in prs} == {427, 285}


def test_merge_pr_success_uses_style_flag(pull_request: PullRequest) -> None:
    """merge_method='squash' translates to tea's --style squash."""
    forge = GiteaForge(login="git.fsfe.org")
    fake_ok = MagicMock(returncode=0, stdout="Merged\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        merge_result = forge.merge_pr(pull_request, method="squash")

    cmd = mock_run.call_args.args[0]
    assert Path(cmd[0]).name == "tea"
    assert cmd[1:3] == ["pulls", "merge"]
    assert cmd[cmd.index("--style") + 1] == "squash"
    assert merge_result.success is True


def test_merge_pr_unknown_method_falls_back_to_merge_style(pull_request: PullRequest) -> None:
    """An unrecognized merge_method value falls back to tea's default 'merge' style."""
    forge = GiteaForge(login="git.fsfe.org")
    fake_ok = MagicMock(returncode=0, stdout="Merged\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        forge.merge_pr(pull_request, method="bogus")

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("--style") + 1] == "merge"


def test_merge_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing tea pulls merge invocation returns a failed MergeResult, not an exception."""
    forge = GiteaForge(login="git.fsfe.org")
    fake_fail = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    with patch("subprocess.run", return_value=fake_fail):
        merge_result = forge.merge_pr(pull_request, method="squash")

    assert merge_result.success is False
    assert "merge conflict" in merge_result.message


def test_approve_pr_success(pull_request: PullRequest) -> None:
    """A successful tea pulls approve invocation returns a successful ApproveResult."""
    forge = GiteaForge(login="git.fsfe.org")
    fake_ok = MagicMock(returncode=0, stdout="https://.../issuecomment-1\n", stderr="")

    with patch("subprocess.run", return_value=fake_ok) as mock_run:
        approve_result = forge.approve_pr(pull_request)

    cmd = mock_run.call_args.args[0]
    assert Path(cmd[0]).name == "tea"
    assert cmd[1:3] == ["pulls", "approve"]
    assert cmd[3] == "427"
    assert approve_result.success is True


def test_approve_pr_failure_does_not_raise(pull_request: PullRequest) -> None:
    """A failing tea pulls approve invocation returns a failed ApproveResult, not raise."""
    forge = GiteaForge(login="git.fsfe.org")
    fake_fail = MagicMock(returncode=1, stdout="", stderr="reviewer required")

    with patch("subprocess.run", return_value=fake_fail):
        approve_result = forge.approve_pr(pull_request)

    assert approve_result.success is False
    assert "reviewer required" in approve_result.message


def test_checkout_pr_resolves_branch_checks_out_and_rebranches(pull_request: PullRequest) -> None:
    """checkout_pr resolves the head branch, runs tea checkout, then git checkout -B onto it.

    tea pulls checkout leaves a detached HEAD (it deliberately bypasses
    any stale local branch of the same name), so a follow-up git command
    puts the user on a real, force-reset, push-ready branch.
    """
    forge = GiteaForge(login="git.fsfe.org")
    head_lookup = MagicMock(returncode=0, stdout=json.dumps(FAKE_PR_JSON))
    tea_checkout = MagicMock(returncode=0, stdout="Checked out\n", stderr="")
    git_checkout = MagicMock(returncode=0, stdout="Switched to a new branch\n", stderr="")

    with patch("subprocess.run", side_effect=[head_lookup, tea_checkout, git_checkout]) as mock_run:
        success, _message = forge.checkout_pr(pull_request)

    assert success is True
    tea_cmd = mock_run.call_args_list[1].args[0]
    assert Path(tea_cmd[0]).name == "tea"
    assert tea_cmd[1:3] == ["pulls", "checkout"]
    assert mock_run.call_args_list[1].kwargs["cwd"] == REPO.local_path

    git_cmd = mock_run.call_args_list[2].args[0]
    assert git_cmd[1:3] == ["checkout", "-B"]
    assert git_cmd[3] == "renovate/postgres-18.x"
    assert git_cmd[4] == "origin/renovate/postgres-18.x"
    assert mock_run.call_args_list[2].kwargs["cwd"] == REPO.local_path


def test_checkout_pr_fails_when_head_branch_unresolvable(pull_request: PullRequest) -> None:
    """If the PR's head branch can't be resolved, checkout_pr fails cleanly, not raises."""
    forge = GiteaForge(login="git.fsfe.org")
    head_lookup = MagicMock(returncode=1, stdout="", stderr="not found")

    with patch("subprocess.run", return_value=head_lookup):
        success, message = forge.checkout_pr(pull_request)

    assert success is False
    assert "head branch" in message.lower()


def test_checkout_pr_fails_when_tea_checkout_fails(pull_request: PullRequest) -> None:
    """A failing tea pulls checkout call is reported, not raised, and git is never invoked."""
    forge = GiteaForge(login="git.fsfe.org")
    head_lookup = MagicMock(returncode=0, stdout=json.dumps(FAKE_PR_JSON))
    tea_checkout = MagicMock(returncode=1, stdout="", stderr="network error")

    with patch("subprocess.run", side_effect=[head_lookup, tea_checkout]) as mock_run:
        success, message = forge.checkout_pr(pull_request)

    assert success is False
    assert "network error" in message
    assert mock_run.call_count == 2  # git checkout -B is never reached
