"""Configuration loading for lsrenovate.

Resolution order for the GitHub token: GITHUB_TOKEN env var, then
github_token_command (e.g. a password manager CLI) in the config file, then
a plaintext github_token in the config file, then nothing (falls back to
gh's own auth state).
"""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "lsrenovate"
DEFAULT_MERGE_METHOD = "squash"
VALID_MERGE_METHODS = {"squash", "merge", "rebase"}
DEFAULT_SORT_BY = "repo"
VALID_SORT_BY = {"repo", "age", "title"}
DEFAULT_LABELS = ["Renovate"]


def config_file_path() -> Path:
    """Return the path to the TOML config file in the platform config dir."""
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def default_myprojects_path() -> Path:
    """Return the default myprojects.yaml path: alongside config.toml."""
    return Path(user_config_dir(APP_NAME)) / "myprojects.yaml"


def _run_token_command(command: list[str]) -> str:
    """Run a configured token-retrieval command and return its trimmed stdout.

    Executed directly via subprocess (no shell), so it works the same
    regardless of the user's login shell (bash, fish, zsh, ...).
    """
    result = subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@dataclass(frozen=True)
class Config:
    """Resolved application configuration."""

    github_token: str | None
    merge_method: str
    myprojects_path: Path
    sort_by: str
    labels: list[str]
    token_command_error: str | None = None


def load_config(path: Path | None = None) -> Config:
    """Load configuration from env vars and the TOML config file.

    Precedence: environment variables win over the config file, which wins
    over built-in defaults.
    """
    path = path or config_file_path()
    file_data: dict = {}
    if path.is_file():
        file_data = tomllib.loads(path.read_text())

    github_token = os.environ.get("GITHUB_TOKEN") or None
    token_command_error: str | None = None
    if not github_token:
        token_command = file_data.get("github_token_command")
        if token_command:
            if not isinstance(token_command, list) or not all(
                isinstance(part, str) for part in token_command
            ):
                msg = f"Invalid github_token_command '{token_command}', must be a list of strings"
                raise ValueError(msg)
            try:
                github_token = _run_token_command(token_command) or None
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                token_command_error = f"github_token_command failed: {exc}"
    if not github_token:
        github_token = file_data.get("github_token") or None

    merge_method = file_data.get("merge_method", DEFAULT_MERGE_METHOD)
    if merge_method not in VALID_MERGE_METHODS:
        msg = f"Invalid merge_method '{merge_method}', must be one of {VALID_MERGE_METHODS}"
        raise ValueError(msg)

    myprojects_path = Path(file_data.get("myprojects_path", default_myprojects_path())).expanduser()

    sort_by = file_data.get("sort_by", DEFAULT_SORT_BY)
    if sort_by not in VALID_SORT_BY:
        msg = f"Invalid sort_by '{sort_by}', must be one of {VALID_SORT_BY}"
        raise ValueError(msg)

    labels = file_data.get("labels", DEFAULT_LABELS)
    if (
        not isinstance(labels, list)
        or not all(isinstance(label, str) for label in labels)
        or not labels
    ):
        msg = f"Invalid labels '{labels}', must be a non-empty list of strings"
        raise ValueError(msg)

    return Config(
        github_token=github_token,
        merge_method=merge_method,
        myprojects_path=myprojects_path,
        sort_by=sort_by,
        labels=labels,
        token_command_error=token_command_error,
    )
