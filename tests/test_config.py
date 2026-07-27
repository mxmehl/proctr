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
