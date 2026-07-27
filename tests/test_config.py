"""Tests for configuration loading."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from pathlib import Path

import pytest

from lsrenovate.config import DEFAULT_LABELS, DEFAULT_MERGE_METHOD, DEFAULT_SORT_BY, load_config


def test_config_env_var_takes_precedence_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GITHUB_TOKEN env var overrides a token set in [github]."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('merge_method = "rebase"\n\n[github]\ntoken = "file-token"\n')

    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    cfg = load_config(config_path)

    assert cfg.github.token == "env-token"
    assert cfg.merge_method == "rebase"


def test_config_defaults_when_no_file_and_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no config file and no env var, built-in defaults are used."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config(Path("/nonexistent/config.toml"))

    assert cfg.github.token is None
    assert cfg.merge_method == DEFAULT_MERGE_METHOD
    assert cfg.sort_by == DEFAULT_SORT_BY
    assert cfg.labels == DEFAULT_LABELS


def test_config_invalid_merge_method_raises(tmp_path: Path) -> None:
    """An unsupported merge_method value in the config file raises ValueError."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('merge_method = "bogus"\n')

    with pytest.raises(ValueError, match="Invalid merge_method"):
        load_config(config_path)


def test_config_invalid_labels_raises(tmp_path: Path) -> None:
    """An empty labels list in the config file raises ValueError."""
    config_path = tmp_path / "config.toml"
    config_path.write_text("labels = []\n")

    with pytest.raises(ValueError, match="Invalid labels"):
        load_config(config_path)


def test_config_github_token_command_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured [github].token_command is executed and its stdout used as the token."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[github]\n"
        'token_command = ["python3", "-c", "print(\\"cmd-token\\")"]\n'
        'token = "plaintext-token"\n'
    )

    cfg = load_config(config_path)

    assert cfg.github.token == "cmd-token"
    assert cfg.github.token_command_error is None


def test_config_env_var_takes_precedence_over_github_token_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GITHUB_TOKEN wins even when [github].token_command is also configured."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[github]\ntoken_command = ["python3", "-c", "print(\\"cmd-token\\")"]\n'
    )

    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    cfg = load_config(config_path)

    assert cfg.github.token == "env-token"


def test_config_github_token_command_failure_falls_back_gracefully(tmp_path: Path) -> None:
    """A failing [github].token_command falls back to the plaintext token, with an error noted."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[github]\n"
        'token_command = ["python3", "-c", "import sys; sys.exit(1)"]\n'
        'token = "plaintext-token"\n'
    )

    cfg = load_config(config_path)

    assert cfg.github.token == "plaintext-token"
    assert cfg.github.token_command_error is not None
    assert "token_command failed" in cfg.github.token_command_error


def test_config_invalid_github_token_command_raises(tmp_path: Path) -> None:
    """A non-list [github].token_command value in the config file raises ValueError."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[github]\ntoken_command = "not-a-list"\n')

    with pytest.raises(ValueError, match="Invalid token_command"):
        load_config(config_path)


def test_config_github_labels_override(tmp_path: Path) -> None:
    """[github].labels overrides the global labels default for the github forge only."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('labels = ["Renovate"]\n\n[github]\nlabels = ["dependencies"]\n')

    cfg = load_config(config_path)

    assert cfg.labels == ["Renovate"]
    assert cfg.github.labels == ["dependencies"]


def test_config_github_labels_default_to_none(tmp_path: Path) -> None:
    """Without an explicit [github].labels, it defaults to None (falls back to global labels)."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[github]\ntoken = "x"\n')

    cfg = load_config(config_path)

    assert cfg.github.labels is None


def test_config_gitlab_instances_parsed_by_host(tmp_path: Path) -> None:
    """Each [gitlab."<host>"] table becomes a GitLabInstanceConfig keyed by host."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[gitlab."gitlab.example.com"]\ntoken = "glpat-abc"\n'
        '[gitlab."gitlab.internal.example.org"]\ntoken = "glpat-def"\n'
    )

    cfg = load_config(config_path)

    assert set(cfg.gitlab_instances) == {"gitlab.example.com", "gitlab.internal.example.org"}
    assert cfg.gitlab_instances["gitlab.example.com"].token == "glpat-abc"
    assert cfg.gitlab_instances["gitlab.internal.example.org"].token == "glpat-def"


def test_config_gitlab_instance_uses_token_command(tmp_path: Path) -> None:
    """A per-instance token_command is executed the same way as the GitHub one."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[gitlab."gitlab.example.com"]\n'
        'token_command = ["python3", "-c", "print(\\"glab-token\\")"]\n'
    )

    cfg = load_config(config_path)

    assert cfg.gitlab_instances["gitlab.example.com"].token == "glab-token"
    assert cfg.gitlab_instances["gitlab.example.com"].token_command_error is None


def test_config_gitlab_instance_api_host_override(tmp_path: Path) -> None:
    """api_host overrides the GITLAB_HOST sent to glab when it differs from the URL host."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[gitlab."gitlab.example.com"]\napi_host = "ssh.gitlab.example.com"\n')

    cfg = load_config(config_path)

    assert cfg.gitlab_instances["gitlab.example.com"].api_host == "ssh.gitlab.example.com"


def test_config_gitlab_instance_api_host_defaults_to_none(tmp_path: Path) -> None:
    """Without an explicit api_host, it defaults to None (dispatcher falls back to the URL host)."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[gitlab."gitlab.example.com"]\ntoken = "x"\n')

    cfg = load_config(config_path)

    assert cfg.gitlab_instances["gitlab.example.com"].api_host is None


def test_config_gitlab_instance_labels_override(tmp_path: Path) -> None:
    """A per-instance labels list overrides the global default for that GitLab host only."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'labels = ["Renovate"]\n\n[gitlab."gitlab.example.com"]\nlabels = ["dependencies"]\n'
    )

    cfg = load_config(config_path)

    assert cfg.labels == ["Renovate"]
    assert cfg.gitlab_instances["gitlab.example.com"].labels == ["dependencies"]


def test_config_no_gitlab_instances_when_absent(tmp_path: Path) -> None:
    """With no [gitlab.*] tables configured, gitlab_instances is empty."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('merge_method = "squash"\n')

    cfg = load_config(config_path)

    assert cfg.gitlab_instances == {}
    assert cfg.gitea_instances == {}


def test_config_gitea_instances_default_login_to_host(tmp_path: Path) -> None:
    """A [gitea."<host>"] table with no explicit login defaults to the host name."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[gitea."gitea.example.com"]\n')

    cfg = load_config(config_path)

    assert cfg.gitea_instances["gitea.example.com"].login == "gitea.example.com"


def test_config_gitea_instance_explicit_login(tmp_path: Path) -> None:
    """An explicit login name in [gitea."<host>"] overrides the host-name default."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[gitea."gitea.example.com"]\nlogin = "my-custom-login"\n')

    cfg = load_config(config_path)

    assert cfg.gitea_instances["gitea.example.com"].login == "my-custom-login"


def test_config_gitea_instance_labels_override(tmp_path: Path) -> None:
    """A per-instance labels list overrides the global default for that Gitea host only."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'labels = ["Renovate"]\n\n[gitea."gitea.example.com"]\nlabels = ["dependencies"]\n'
    )

    cfg = load_config(config_path)

    assert cfg.labels == ["Renovate"]
    assert cfg.gitea_instances["gitea.example.com"].labels == ["dependencies"]
