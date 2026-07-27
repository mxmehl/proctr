"""Configuration loading for lsrenovate.

Resolution order for the GitHub token: GITHUB_TOKEN env var, then
[github].token_command (e.g. a password manager CLI) in the config file,
then a plaintext [github].token in the config file, then nothing (falls
back to gh's own auth state).
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


def _resolve_token(
    table_data: dict, *, env_var: str | None = None
) -> tuple[str | None, str | None]:
    """Resolve a token from an env var, a token_command, or a plaintext value.

    Precedence: env var (if given) > token_command > plaintext token.
    Returns (token, error) where error is set (non-fatal) if a configured
    token_command failed, in which case resolution falls through to the
    plaintext value.
    """
    token = os.environ.get(env_var) if env_var else None
    if token:
        return token, None

    error: str | None = None
    token_command = table_data.get("token_command")
    if token_command:
        if not isinstance(token_command, list) or not all(
            isinstance(part, str) for part in token_command
        ):
            msg = f"Invalid token_command '{token_command}', must be a list of strings"
            raise ValueError(msg)
        try:
            token = _run_token_command(token_command) or None
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            error = f"token_command failed: {exc}"

    if not token:
        token = table_data.get("token") or None

    return token, error


def _validate_labels(labels: object, *, context: str) -> list[str]:
    """Validate a labels value, returning it unchanged if it's a non-empty list of strings."""
    if not isinstance(labels, list) or not labels:
        msg = f"Invalid {context} '{labels}', must be a non-empty list of strings"
        raise ValueError(msg)
    validated: list[str] = [item for item in labels if isinstance(item, str)]
    if len(validated) != len(labels):
        msg = f"Invalid {context} '{labels}', must be a non-empty list of strings"
        raise ValueError(msg)
    return validated


@dataclass(frozen=True)
class GitHubConfig:
    """GitHub credentials and label filter, resolved from the [github] table."""

    token: str | None
    labels: list[str] | None = None
    token_command_error: str | None = None


@dataclass(frozen=True)
class GitLabInstanceConfig:
    """Per-host GitLab credentials, resolved the same way as the GitHub token.

    api_host overrides the value sent as GITLAB_HOST to `glab`, for the
    case where glab's own stored auth is keyed under a different hostname
    than the one used in myprojects.yaml URLs (e.g. glab auth login was
    run against an SSH-style host like "ssh.gitlab.example.com" while
    repo URLs use the plain API host "gitlab.example.com"). Defaults to
    the table's own host key when not set.
    """

    token: str | None
    api_host: str | None = None
    labels: list[str] | None = None
    token_command_error: str | None = None


@dataclass(frozen=True)
class GiteaInstanceConfig:
    """Per-host Gitea settings.

    lsrenovate never handles Gitea tokens directly: register the instance
    with `tea login add` yourself first, then reference that login name
    here (defaults to the host itself, which is tea's own naming
    convention when you name logins after their host).
    """

    login: str
    labels: list[str] | None = None


@dataclass(frozen=True)
class Config:
    """Resolved application configuration."""

    github: GitHubConfig
    merge_method: str
    myprojects_path: Path
    sort_by: str
    labels: list[str]
    gitlab_instances: dict[str, GitLabInstanceConfig]
    gitea_instances: dict[str, GiteaInstanceConfig]


def _load_github_config(file_data: dict) -> GitHubConfig:
    """Parse the [github] table into a GitHubConfig."""
    table = file_data.get("github", {})
    if not isinstance(table, dict):
        msg = 'Invalid "github" entry, must be a table'
        raise TypeError(msg)
    token, error = _resolve_token(table, env_var="GITHUB_TOKEN")
    labels = table.get("labels")
    if labels is not None:
        labels = _validate_labels(labels, context="github.labels")
    return GitHubConfig(token=token, labels=labels, token_command_error=error)


def _load_gitlab_instances(file_data: dict) -> dict[str, GitLabInstanceConfig]:
    """Parse the [gitlab."<host>"] tables into per-host GitLab configs."""
    instances: dict[str, GitLabInstanceConfig] = {}
    for host, table in file_data.get("gitlab", {}).items():
        if not isinstance(table, dict):
            msg = f'Invalid gitlab."{host}" entry, must be a table'
            raise TypeError(msg)
        token, error = _resolve_token(table)
        api_host = table.get("api_host")
        if api_host is not None and (not isinstance(api_host, str) or not api_host):
            msg = f"Invalid gitlab.\"{host}\".api_host '{api_host}', must be a non-empty string"
            raise ValueError(msg)
        labels = table.get("labels")
        if labels is not None:
            labels = _validate_labels(labels, context=f'gitlab."{host}".labels')
        instances[host] = GitLabInstanceConfig(
            token=token, api_host=api_host, labels=labels, token_command_error=error
        )
    return instances


def _load_gitea_instances(file_data: dict) -> dict[str, GiteaInstanceConfig]:
    """Parse the [gitea."<host>"] tables into per-host Gitea configs.

    `login` defaults to the host itself, matching the convention of naming
    `tea login add --name` after the instance's hostname.
    """
    instances: dict[str, GiteaInstanceConfig] = {}
    for host, table in file_data.get("gitea", {}).items():
        if not isinstance(table, dict):
            msg = f'Invalid gitea."{host}" entry, must be a table'
            raise TypeError(msg)
        login = table.get("login", host)
        if not isinstance(login, str) or not login:
            msg = f"Invalid gitea.\"{host}\".login '{login}', must be a non-empty string"
            raise ValueError(msg)
        labels = table.get("labels")
        if labels is not None:
            labels = _validate_labels(labels, context=f'gitea."{host}".labels')
        instances[host] = GiteaInstanceConfig(login=login, labels=labels)
    return instances


def load_config(path: Path | None = None) -> Config:
    """Load configuration from env vars and the TOML config file.

    Precedence: environment variables win over the config file, which wins
    over built-in defaults.
    """
    path = path or config_file_path()
    file_data: dict = {}
    if path.is_file():
        file_data = tomllib.loads(path.read_text())

    merge_method = file_data.get("merge_method", DEFAULT_MERGE_METHOD)
    if merge_method not in VALID_MERGE_METHODS:
        msg = f"Invalid merge_method '{merge_method}', must be one of {VALID_MERGE_METHODS}"
        raise ValueError(msg)

    myprojects_path = Path(file_data.get("myprojects_path", default_myprojects_path())).expanduser()

    sort_by = file_data.get("sort_by", DEFAULT_SORT_BY)
    if sort_by not in VALID_SORT_BY:
        msg = f"Invalid sort_by '{sort_by}', must be one of {VALID_SORT_BY}"
        raise ValueError(msg)

    labels = _validate_labels(file_data.get("labels", DEFAULT_LABELS), context="labels")

    return Config(
        github=_load_github_config(file_data),
        merge_method=merge_method,
        myprojects_path=myprojects_path,
        sort_by=sort_by,
        labels=labels,
        gitlab_instances=_load_gitlab_instances(file_data),
        gitea_instances=_load_gitea_instances(file_data),
    )
