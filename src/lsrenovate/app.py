"""Textual TUI application for managing open Renovate PRs."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import asyncio
import os
import subprocess
import webbrowser
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header

if TYPE_CHECKING:
    from textual.widgets.data_table import ColumnKey

from lsrenovate.config import load_config
from lsrenovate.fetch import fetch_all_prs
from lsrenovate.forges.github import GitHubForge
from lsrenovate.projects import load_repos

if TYPE_CHECKING:
    from lsrenovate.config import Config
    from lsrenovate.fetch import FetchResult
    from lsrenovate.forges.base import MergeResult, PullRequest

COLUMNS = ("Sel", "Repo", "Title", "Age", "Merge state", "Mergeable", "PR")
CHECKED = "[X]"
UNCHECKED = "[ ]"
TITLE_MAX_LEN = 40
READY_MERGEABLE = "MERGEABLE"
READY_MERGE_STATE = "CLEAN"

SORT_KEYS: dict[str, tuple[str, ...]] = {
    "repo": ("repo", "created_at"),
    "age": ("created_at",),
    "title": ("title",),
}
DEFAULT_SORT_BY = "repo"


def _sort_value(pr: PullRequest, field: str) -> str | datetime:
    """Return the sortable value for a PR's given field name."""
    if field == "repo":
        return pr.repo.full_name
    return getattr(pr, field)


def _truncate(text: str, max_len: int = TITLE_MAX_LEN) -> str:
    """Truncate text to max_len chars, adding an ellipsis marker if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _format_age(created_at: datetime) -> str:
    """Return a short human-readable age string, e.g. '3d' or '5h'."""
    delta = datetime.now(UTC) - created_at
    days = delta.days
    if days > 0:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h"
    minutes = delta.seconds // 60
    return f"{minutes}m"


def _pr_key(pr: PullRequest) -> str:
    """Return the unique row/selection key for a PR."""
    return f"{pr.repo.full_name}#{pr.number}"


def _is_ready_to_merge(pr: PullRequest) -> bool:
    """Return whether a PR's mergeable/merge state indicate it's ready to merge."""
    return pr.mergeable == READY_MERGEABLE and pr.merge_state_status == READY_MERGE_STATE


def _status_cell(value: str, *, ready: bool) -> Text:
    """Render a status value in green if ready to merge, red otherwise."""
    return Text(value, style="bold green" if ready else "bold red")


def build_merge_summary(results: list[MergeResult]) -> str:
    """Build a human-readable summary line from a batch of merge results."""
    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    lines = [f"Merged {len(succeeded)}/{len(results)} PR(s)."]
    lines.extend(f"  FAILED {_pr_key(r.pull_request)}: {r.message}" for r in failed)
    return "\n".join(lines)


class LsRenovateApp(App[None]):
    """Lists open Renovate PRs across all configured GitHub repos."""

    TITLE = "lsrenovate"
    BINDINGS: ClassVar = [
        ("r", "refresh_prs", "Refresh"),
        ("space", "toggle_selection", "Select"),
        ("o", "open_browser", "Open in browser"),
        ("s", "open_shell", "Open shell"),
        ("t", "cycle_sort", "Sort"),
        ("m", "merge_selected", "Merge"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config | None = None) -> None:
        """Initialize the app, resolving configuration and the GitHub forge adapter."""
        super().__init__()
        self.config = config or load_config()
        self.forge = GitHubForge(github_token=self.config.github_token, labels=self.config.labels)
        self.pull_requests: list[PullRequest] = []
        self.selected: set[str] = set()
        self._sel_column_key: ColumnKey | None = None  # set in on_mount
        self.sort_by = self.config.sort_by if self.config.sort_by in SORT_KEYS else DEFAULT_SORT_BY

    def compose(self) -> ComposeResult:
        """Build the app's widget tree."""
        yield Header()
        with Container():
            yield DataTable(id="pr-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the table columns and trigger the initial PR fetch."""
        if self.config.token_command_error:
            self.notify(self.config.token_command_error, severity="warning", timeout=10)
        table = self.query_one(DataTable)
        column_keys = table.add_columns(*COLUMNS)
        self._sel_column_key = column_keys[COLUMNS.index("Sel")]
        self.app_resume_signal.subscribe(self, self._on_app_resume)
        self.action_refresh_prs()

    def _on_app_resume(self, _app: LsRenovateApp) -> None:
        """Force a full redraw after returning from a suspended shell.

        ponytail: the terminal can be left in an inconsistent state by
        whatever ran while suspended (shell prompt, clear, etc.); a full
        refresh() is the simple fix rather than trying to diff what changed.
        """
        self.refresh(layout=True)

    def action_refresh_prs(self) -> None:
        """Kick off a background fetch of all Renovate PRs."""
        self.sub_title = "Refreshing…"
        self.run_worker(self._fetch_and_populate(), exclusive=True)

    def action_cycle_sort(self) -> None:
        """Cycle through available sort modes and re-render the table."""
        keys = list(SORT_KEYS)
        next_index = (keys.index(self.sort_by) + 1) % len(keys)
        self.sort_by = keys[next_index]
        self._render_table()
        self.notify(f"Sorted by {self.sort_by}", timeout=2)

    async def _fetch_and_populate(self) -> None:
        repos = load_repos(self.config.myprojects_path, forge="github")
        result: FetchResult = await asyncio.to_thread(fetch_all_prs, repos, self.forge)
        self._populate_table(result)

    def _populate_table(self, result: FetchResult) -> None:
        self.pull_requests = result.pull_requests
        valid_keys = {_pr_key(pr) for pr in self.pull_requests}
        self.selected &= valid_keys  # drop selections for PRs that no longer exist
        self._render_table()

        error_note = f", {len(result.errors)} repo error(s)" if result.errors else ""
        self.sub_title = f"{len(self.pull_requests)} open Renovate PR(s){error_note}"
        if result.errors:
            for err in result.errors:
                self.notify(f"{err.repo.full_name}: {err.error}", severity="warning", timeout=8)

    def _render_table(self) -> None:
        """Re-sort (per self.sort_by) and redraw the table from self.pull_requests."""
        sort_fields = SORT_KEYS[self.sort_by]
        ordered = sorted(
            self.pull_requests,
            key=lambda pr: tuple(_sort_value(pr, field) for field in sort_fields),
        )

        table = self.query_one(DataTable)
        table.clear()
        for pr in ordered:
            key = _pr_key(pr)
            ready = _is_ready_to_merge(pr)
            table.add_row(
                CHECKED if key in self.selected else UNCHECKED,
                pr.repo.full_name,
                _truncate(pr.title),
                _format_age(pr.created_at),
                _status_cell(pr.merge_state_status, ready=ready),
                _status_cell(pr.mergeable, ready=ready),
                str(pr.number),
                key=key,
            )

    def _pr_for_key(self, key: str) -> PullRequest | None:
        return next((pr for pr in self.pull_requests if _pr_key(pr) == key), None)

    def _selected_or_focused_prs(self) -> list[PullRequest]:
        """Return selected PRs, or the currently focused row's PR if none selected."""
        if self.selected:
            return [pr for pr in self.pull_requests if _pr_key(pr) in self.selected]
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return []
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        pr = self._pr_for_key(str(row_key.value))
        return [pr] if pr else []

    def action_toggle_selection(self) -> None:
        """Toggle selection of the row under the cursor."""
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        assert self._sel_column_key is not None, (  # noqa: S101
            "on_mount must run before toggling selection"
        )
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key = str(row_key.value)
        if key in self.selected:
            self.selected.discard(key)
            table.update_cell(row_key, self._sel_column_key, UNCHECKED)
        else:
            self.selected.add(key)
            table.update_cell(row_key, self._sel_column_key, CHECKED)

    def action_open_browser(self) -> None:
        """Open the selected (or focused) PR(s) in the default web browser."""
        prs = self._selected_or_focused_prs()
        if not prs:
            self.notify("No PR selected or focused", severity="warning")
            return
        for pr in prs:
            webbrowser.open(pr.url)

    def action_merge_selected(self) -> None:
        """Merge the selected (or focused) PR(s) sequentially, then refresh."""
        prs = self._selected_or_focused_prs()
        if not prs:
            self.notify("No PR selected or focused", severity="warning")
            return
        self.run_worker(self._merge_and_refresh(prs), exclusive=True)

    async def _merge_and_refresh(self, prs: list[PullRequest]) -> None:
        method = self.config.merge_method
        results: list[MergeResult] = []
        for pr in prs:
            result = await asyncio.to_thread(self.forge.merge_pr, pr, method=method)
            results.append(result)

        summary = build_merge_summary(results)
        any_failed = any(not r.success for r in results)
        self.notify(summary, severity="warning" if any_failed else "information", timeout=10)

        self.selected.clear()
        await self._fetch_and_populate()

    def action_open_shell(self) -> None:
        """Suspend the TUI and open a shell at the focused PR's local repo path.

        Always acts on the row under the cursor, ignoring multi-selection —
        opening one shell per selected repo doesn't make sense here.

        ponytail: App.suspend() + exec of an interactive shell can't be
        meaningfully exercised under Textual's headless test harness (no
        real TTY to hand off). Verified via mocked subprocess.run/suspend
        (correct cwd/env) plus manual interactive confirmation.
        """
        table = self.query_one(DataTable)
        if table.row_count == 0:
            self.notify("No PR focused", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        pr = self._pr_for_key(str(row_key.value))
        if pr is None:
            return

        local_path = pr.repo.local_path
        if not local_path.is_dir():
            self.notify(f"Local path does not exist: {local_path}", severity="error")
            return

        shell = os.environ.get("SHELL", "/bin/sh")
        env = dict(os.environ)
        if self.config.github_token:
            env["GITHUB_TOKEN"] = self.config.github_token
        with self.suspend():
            subprocess.run([shell], cwd=local_path, env=env, check=False)  # noqa: S603


def main() -> None:
    """Run the lsrenovate TUI application."""
    LsRenovateApp().run()


if __name__ == "__main__":
    main()
