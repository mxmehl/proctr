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

import jsonschema
from platformdirs import user_config_dir

APP_NAME = "lsrenovate"
DEFAULT_MERGE_METHOD = "squash"
VALID_MERGE_METHODS = {"squash", "merge", "rebase"}
DEFAULT_SORT_BY = "repo"
VALID_SORT_BY = {"repo", "age", "title"}
DEFAULT_LABELS = ["Renovate"]
DEFAULT_MATCH_MODE = "and"
VALID_MATCH_MODES = {"and", "or"}

# Shared by the global config and every [github]/[gitlab."host"]/[gitea."host"] table:
# a PR is matched by `labels` (AND semantics) and/or `branch_prefixes` (OR semantics),
# combined per `match_mode`. See README for the full semantics.
_FILTER_PROPERTIES = {
    "labels": {"type": "array", "items": {"type": "string"}},
    "branch_prefixes": {"type": "array", "items": {"type": "string"}},
    "match_mode": {"type": "string", "enum": sorted(VALID_MATCH_MODES)},
}

# Validates structure/types/enums only (TOML shape, allowed values, table keys).
# Cross-field logic (token precedence, login/api_host defaulting, "at least one
# filter enabled") is Python-side, in load_config() and ForgeDispatcher._build.
CONFIG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "merge_method": {"type": "string", "enum": sorted(VALID_MERGE_METHODS)},
        "sort_by": {"type": "string", "enum": sorted(VALID_SORT_BY)},
        "myprojects_path": {"type": "string"},
        **_FILTER_PROPERTIES,
        "github": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "token": {"type": "string"},
                "token_command": {"type": "array", "items": {"type": "string"}},
                **_FILTER_PROPERTIES,
            },
        },
        "gitlab": {
            "type": "object",
            "patternProperties": {
                ".*": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "token": {"type": "string"},
                        "token_command": {"type": "array", "items": {"type": "string"}},
                        "api_host": {"type": "string", "minLength": 1},
                        **_FILTER_PROPERTIES,
                    },
                },
            },
        },
        "gitea": {
            "type": "object",
            "patternProperties": {
                ".*": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "login": {"type": "string", "minLength": 1},
                        **_FILTER_PROPERTIES,
                    },
                },
            },
        },
    },
}


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


def _resolve_table_filters(
    table: dict,
) -> tuple[list[str] | None, list[str] | None, str | None]:
    """Resolve (labels, branch_prefixes, match_mode) overrides from a table.

    Schema validation already guarantees types, so this only applies the
    "implicit disable" rule: setting `branch_prefixes` without `labels` at
    the same level means labels are disabled at that level (`[]`), not
    inherited from a higher level. Returns None for a field that isn't set
    at all at this level (signalling "inherit from the level above").
    """
    labels = table.get("labels")
    if labels is None and "branch_prefixes" in table:
        labels = []
    branch_prefixes = table.get("branch_prefixes")
    match_mode = table.get("match_mode")
    return labels, branch_prefixes, match_mode


@dataclass(frozen=True)
class GitHubConfig:
    """GitHub credentials and PR filter overrides, resolved from the [github] table."""

    token: str | None
    labels: list[str] | None = None
    branch_prefixes: list[str] | None = None
    match_mode: str | None = None
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
    branch_prefixes: list[str] | None = None
    match_mode: str | None = None
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
    branch_prefixes: list[str] | None = None
    match_mode: str | None = None


@dataclass(frozen=True)
class Config:
    """Resolved application configuration."""

    github: GitHubConfig
    merge_method: str
    myprojects_path: Path
    sort_by: str
    labels: list[str]
    branch_prefixes: list[str]
    match_mode: str
    gitlab_instances: dict[str, GitLabInstanceConfig]
    gitea_instances: dict[str, GiteaInstanceConfig]


def _load_github_config(file_data: dict) -> GitHubConfig:
    """Parse the [github] table into a GitHubConfig."""
    table = file_data.get("github", {})
    token, error = _resolve_token(table, env_var="GITHUB_TOKEN")
    labels, branch_prefixes, match_mode = _resolve_table_filters(table)
    return GitHubConfig(
        token=token,
        labels=labels,
        branch_prefixes=branch_prefixes,
        match_mode=match_mode,
        token_command_error=error,
    )


def _load_gitlab_instances(file_data: dict) -> dict[str, GitLabInstanceConfig]:
    """Parse the [gitlab."<host>"] tables into per-host GitLab configs."""
    instances: dict[str, GitLabInstanceConfig] = {}
    for host, table in file_data.get("gitlab", {}).items():
        token, error = _resolve_token(table)
        labels, branch_prefixes, match_mode = _resolve_table_filters(table)
        instances[host] = GitLabInstanceConfig(
            token=token,
            api_host=table.get("api_host"),
            labels=labels,
            branch_prefixes=branch_prefixes,
            match_mode=match_mode,
            token_command_error=error,
        )
    return instances


def _load_gitea_instances(file_data: dict) -> dict[str, GiteaInstanceConfig]:
    """Parse the [gitea."<host>"] tables into per-host Gitea configs.

    `login` defaults to the host itself, matching the convention of naming
    `tea login add --name` after the instance's hostname.
    """
    instances: dict[str, GiteaInstanceConfig] = {}
    for host, table in file_data.get("gitea", {}).items():
        labels, branch_prefixes, match_mode = _resolve_table_filters(table)
        instances[host] = GiteaInstanceConfig(
            login=table.get("login", host),
            labels=labels,
            branch_prefixes=branch_prefixes,
            match_mode=match_mode,
        )
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

    jsonschema.validate(instance=file_data, schema=CONFIG_SCHEMA)

    merge_method = file_data.get("merge_method", DEFAULT_MERGE_METHOD)
    myprojects_path = Path(file_data.get("myprojects_path", default_myprojects_path())).expanduser()
    sort_by = file_data.get("sort_by", DEFAULT_SORT_BY)
    match_mode = file_data.get("match_mode", DEFAULT_MATCH_MODE)

    labels, branch_prefixes, _ = _resolve_table_filters(file_data)
    if labels is None:
        labels = list(DEFAULT_LABELS)
    branch_prefixes = branch_prefixes or []

    return Config(
        github=_load_github_config(file_data),
        merge_method=merge_method,
        myprojects_path=myprojects_path,
        sort_by=sort_by,
        labels=labels,
        branch_prefixes=branch_prefixes,
        match_mode=match_mode,
        gitlab_instances=_load_gitlab_instances(file_data),
        gitea_instances=_load_gitea_instances(file_data),
    )
