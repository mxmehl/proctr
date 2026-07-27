"""Tests for configuration loading."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from pathlib import Path

import pytest

from lsrenovate.config import DEFAULT_LABELS, DEFAULT_MERGE_METHOD, DEFAULT_SORT_BY, load_config


def test_config_env_var_takes_precedence_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GITHUB_TOKEN env var overrides a token set in the config file."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('github_token = "file-token"\nmerge_method = "rebase"\n')

    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    cfg = load_config(config_path)

    assert cfg.github_token == "env-token"
    assert cfg.merge_method == "rebase"


def test_config_defaults_when_no_file_and_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no config file and no env var, built-in defaults are used."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config(Path("/nonexistent/config.toml"))

    assert cfg.github_token is None
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


def test_config_token_command_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured github_token_command is executed and its stdout used as the token."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'github_token_command = ["python3", "-c", "print(\\"cmd-token\\")"]\n'
        'github_token = "plaintext-token"\n'
    )

    cfg = load_config(config_path)

    assert cfg.github_token == "cmd-token"
    assert cfg.token_command_error is None


def test_config_env_var_takes_precedence_over_token_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GITHUB_TOKEN wins even when a github_token_command is also configured."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('github_token_command = ["python3", "-c", "print(\\"cmd-token\\")"]\n')

    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    cfg = load_config(config_path)

    assert cfg.github_token == "env-token"


def test_config_token_command_failure_falls_back_gracefully(tmp_path: Path) -> None:
    """A failing github_token_command falls back to the plaintext token, with an error noted."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'github_token_command = ["python3", "-c", "import sys; sys.exit(1)"]\n'
        'github_token = "plaintext-token"\n'
    )

    cfg = load_config(config_path)

    assert cfg.github_token == "plaintext-token"
    assert cfg.token_command_error is not None
    assert "github_token_command failed" in cfg.token_command_error


def test_config_invalid_token_command_raises(tmp_path: Path) -> None:
    """A non-list github_token_command value in the config file raises ValueError."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('github_token_command = "not-a-list"\n')

    with pytest.raises(ValueError, match="Invalid github_token_command"):
        load_config(config_path)
