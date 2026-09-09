"""Tests for the merge summary builder."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import proctr.app as app_module
from proctr.app import (
    ProctrApp,
    _mergeable_cell,
    _pipeline_cell,
    _review_cell,
    build_approve_summary,
    build_merge_summary,
    configure_logging,
    logger,
)
from proctr.config import Config, GitHubConfig
from proctr.demo import demo_pull_requests
from proctr.forges.base import ApproveResult, MergeResult, PullRequest
from proctr.projects import Repo

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


def test_demo_pull_requests_covers_every_review_and_pipeline_state() -> None:
    """--demo's sample data exercises every column color so a screenshot shows them all."""
    prs = demo_pull_requests()

    assert len(prs) > 0
    assert {pr.repo.forge for pr in prs} == {"github", "gitlab", "gitea"}
    assert {pr.pipeline_status for pr in prs} >= {"CLEAN", "UNSTABLE", "failed", "success"}
    assert {pr.review_decision for pr in prs} >= {
        "APPROVED",
        "REVIEW_REQUIRED",
        "CHANGES_REQUESTED",
        "",
    }


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
    for value in ("N/A", "running", "pending"):
        assert str(_pipeline_cell(value).style) == ""


def test_pipeline_cell_red_for_blocked() -> None:
    """GitHub's mergeStateStatus=BLOCKED (e.g. unmet required reviews/checks) renders red."""
    assert str(_pipeline_cell("BLOCKED").style) == "bold red"


def test_review_cell_green_for_approved() -> None:
    """reviewDecision=APPROVED renders green."""
    assert str(_review_cell("APPROVED").style) == "bold green"


def test_review_cell_red_for_review_required_or_changes_requested() -> None:
    """A reviewDecision of REVIEW_REQUIRED or CHANGES_REQUESTED renders red."""
    for value in ("REVIEW_REQUIRED", "CHANGES_REQUESTED"):
        assert str(_review_cell(value).style) == "bold red"


def test_review_cell_plain_none_for_empty_string() -> None:
    """An empty reviewDecision (gitlab/gitea don't populate this field) shows plain 'None'."""
    cell = _review_cell("")
    assert str(cell.style) == ""
    assert str(cell) == "None"


def test_build_approve_summary_all_success() -> None:
    """An all-success batch reports N/N approved with no failure lines."""
    results = [
        ApproveResult(pull_request=_pr(1), success=True, message="Approved"),
        ApproveResult(pull_request=_pr(2), success=True, message="Approved"),
    ]
    summary = build_approve_summary(results)
    assert "Approved 2/2 PR(s)." in summary
    assert "FAILED" not in summary


def test_build_approve_summary_mixed_results() -> None:
    """A mixed batch reports the correct ratio and one FAILED line per failure."""
    results = [
        ApproveResult(pull_request=_pr(1), success=True, message="Approved"),
        ApproveResult(pull_request=_pr(2), success=False, message="not permitted"),
    ]
    summary = build_approve_summary(results)
    assert "Approved 1/2 PR(s)." in summary
    assert "FAILED mxmehl/my-tool#2: not permitted" in summary


@pytest.fixture
def app_for_merge() -> ProctrApp:
    """A minimal ProctrApp stand-in with notify/resolve_forge/config mocked out.

    Avoids spinning up the real Textual app harness (no widgets are
    touched by _merge_and_refresh besides notify/sub_title) while still
    exercising the real method under test. sub_title is a Textual
    reactive that requires the App's DOM machinery to be initialized, so
    it's shadowed with a plain instance attribute here.
    """
    app = ProctrApp.__new__(ProctrApp)
    app.notify = MagicMock()
    app.config = MagicMock(merge_method="squash")
    app.selected = set()
    app.__dict__["sub_title"] = ""

    async def fake_fetch_and_populate() -> None:
        pass

    app._fetch_and_populate = fake_fetch_and_populate
    return app


def test_merge_single_pr_skips_progress_notifications(app_for_merge: ProctrApp) -> None:
    """A single-PR merge only gets the final summary, not batch-progress noise."""
    pr = _pr(1)
    forge = MagicMock()
    forge.merge_pr.return_value = MergeResult(pull_request=pr, success=True, message="Merged")
    app_for_merge.resolve_forge = lambda repo: forge

    asyncio.run(app_for_merge._merge_and_refresh([pr]))

    messages = [call.args[0] for call in app_for_merge.notify.call_args_list]
    assert len(messages) == 1
    assert "Merged 1/1 PR(s)." in messages[0]


def test_approve_single_pr_skips_progress_notifications(app_for_merge: ProctrApp) -> None:
    """A single-PR approve only gets the final summary, not batch-progress noise."""
    pr = _pr(1)
    forge = MagicMock()
    forge.approve_pr.return_value = ApproveResult(pull_request=pr, success=True, message="Approved")
    app_for_merge.resolve_forge = lambda repo: forge

    asyncio.run(app_for_merge._approve_and_refresh([pr]))

    messages = [call.args[0] for call in app_for_merge.notify.call_args_list]
    assert len(messages) == 1
    assert "Approved 1/1 PR(s)." in messages[0]


def test_merge_batch_reports_start_and_per_pr_progress() -> None:
    """A multi-PR merge notifies the batch start and each PR's outcome as it completes.

    Uses the real Textual app harness (run_test) with a real ProctrApp
    instance, since sub_title is a reactive property that needs the App's
    DOM machinery initialized (via App.__init__) before it can be assigned
    — a bare __new__() instance can't set it.
    """

    async def scenario() -> list[str]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as myprojects_file:
            myprojects_file.write("myprojects: {}\n")
            myprojects_path = Path(myprojects_file.name)

        config = Config(
            github=GitHubConfig(token=None),
            merge_method="squash",
            myprojects_path=myprojects_path,
            sort_by="repo",
            labels=["Renovate"],
            branch_prefixes=[],
            match_mode="and",
            gitlab_instances={},
            gitea_instances={},
        )
        app = ProctrApp(config=config)
        prs = [_pr(1), _pr(2), _pr(3)]
        forge = MagicMock()
        forge.merge_pr.side_effect = [
            MergeResult(pull_request=prs[0], success=True, message="Merged"),
            MergeResult(pull_request=prs[1], success=False, message="conflict"),
            MergeResult(pull_request=prs[2], success=True, message="Merged"),
        ]
        app.resolve_forge = lambda repo: forge

        async def fake_fetch_and_populate() -> None:
            pass

        app._fetch_and_populate = fake_fetch_and_populate

        async with app.run_test():
            app.notify = MagicMock()
            await app._merge_and_refresh(prs)
        myprojects_path.unlink(missing_ok=True)
        return [call.args[0] for call in app.notify.call_args_list]

    messages = asyncio.run(scenario())
    assert messages[0] == "Merging 3 PR(s)…"
    assert "[1/3] Merged mxmehl/my-tool#1" in messages[1]
    assert "[2/3] FAILED mxmehl/my-tool#2: conflict" in messages[2]
    assert "[3/3] Merged mxmehl/my-tool#3" in messages[3]
    assert "Merged 2/3 PR(s)." in messages[4]


def test_main_bare_invocation_runs_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no subcommand, main() constructs and runs ProctrApp as before."""
    monkeypatch.setattr(sys, "argv", ["proctr"])
    mock_app = MagicMock()
    mock_app_cls = MagicMock(return_value=mock_app)
    monkeypatch.setattr(app_module, "ProctrApp", mock_app_cls)

    app_module.main()

    mock_app_cls.assert_called_once_with(demo=False)
    mock_app.run.assert_called_once()


def test_main_config_myprojects_dispatches_and_skips_tui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`config myprojects` calls generate_myprojects and never constructs ProctrApp."""
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    output = tmp_path / "out.yaml"
    monkeypatch.setattr(
        sys,
        "argv",
        ["proctr", "config", "myprojects", "--root-dir", str(root_dir), "-o", str(output)],
    )
    mock_generate = MagicMock()
    monkeypatch.setattr(app_module, "generate_myprojects", mock_generate)
    mock_app_cls = MagicMock()
    monkeypatch.setattr(app_module, "ProctrApp", mock_app_cls)

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 0
    mock_generate.assert_called_once_with(root_dir, output, force=False)
    mock_app_cls.assert_not_called()


def test_main_config_myprojects_defaults_to_configured_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without -o/--output, the configured myprojects_path from config.toml is used."""
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    configured_path = tmp_path / "configured-myprojects.yaml"
    monkeypatch.setattr(
        sys, "argv", ["proctr", "config", "myprojects", "--root-dir", str(root_dir)]
    )
    monkeypatch.setattr(
        app_module,
        "load_config",
        MagicMock(
            return_value=Config(
                github=GitHubConfig(token=None),
                merge_method="squash",
                myprojects_path=configured_path,
                sort_by="repo",
                labels=[],
                branch_prefixes=[],
                match_mode="and",
                gitlab_instances={},
                gitea_instances={},
            )
        ),
    )
    mock_generate = MagicMock()
    monkeypatch.setattr(app_module, "generate_myprojects", mock_generate)

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 0
    mock_generate.assert_called_once_with(root_dir, configured_path, force=False)


def test_main_config_myprojects_rejects_non_directory_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A --root-dir that isn't a directory exits with an error, without calling generate."""
    not_a_dir = tmp_path / "nope"
    monkeypatch.setattr(
        sys, "argv", ["proctr", "config", "myprojects", "--root-dir", str(not_a_dir)]
    )
    mock_generate = MagicMock()
    monkeypatch.setattr(app_module, "generate_myprojects", mock_generate)

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 1
    mock_generate.assert_not_called()


def test_main_config_myprojects_reports_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A FileExistsError from generate_myprojects becomes exit code 1, not a traceback."""
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    output = tmp_path / "out.yaml"
    monkeypatch.setattr(
        sys,
        "argv",
        ["proctr", "config", "myprojects", "--root-dir", str(root_dir), "-o", str(output)],
    )
    monkeypatch.setattr(
        app_module,
        "generate_myprojects",
        MagicMock(side_effect=FileExistsError("already exists")),
    )

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 1


def test_main_config_set_dispatches_and_skips_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    """`config set` calls set_config_value and never constructs ProctrApp."""
    monkeypatch.setattr(sys, "argv", ["proctr", "config", "set", "merge_method", "rebase"])
    mock_set = MagicMock()
    monkeypatch.setattr(app_module, "set_config_value", mock_set)
    mock_app_cls = MagicMock()
    monkeypatch.setattr(app_module, "ProctrApp", mock_app_cls)

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 0
    mock_set.assert_called_once_with("merge_method", "rebase")
    mock_app_cls.assert_not_called()


def test_configure_logging_writes_to_log_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """configure_logging() sets up a FileHandler at log_file_path(), and _notify writes to it."""
    log_path = tmp_path / "logs" / "proctr.log"
    monkeypatch.setattr(app_module, "log_file_path", lambda: log_path)
    # Reset any handler a previous test/run may have attached to the shared logger.
    logger.handlers.clear()

    configure_logging()
    try:
        myprojects_path = tmp_path / "myprojects.yaml"
        myprojects_path.write_text("myprojects: {}\n")
        config = Config(
            github=GitHubConfig(token=None),
            merge_method="squash",
            myprojects_path=myprojects_path,
            sort_by="repo",
            labels=[],
            branch_prefixes=[],
            match_mode="and",
            gitlab_instances={},
            gitea_instances={},
        )
        app = ProctrApp(config=config)

        async def scenario() -> None:
            async with app.run_test():
                app.notify = MagicMock()
                app._notify("disk on fire", severity="error")

        asyncio.run(scenario())
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()

    assert log_path.is_file()
    assert "ERROR disk on fire" in log_path.read_text()
