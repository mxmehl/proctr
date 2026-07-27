"""Minimal assert-based self-check for config and projects loading.

Run with: uv run python tests/test_task1.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from lsrenovate.config import DEFAULT_LABELS, DEFAULT_MERGE_METHOD, DEFAULT_SORT_BY, load_config
from lsrenovate.projects import load_repos

FIXTURE_YAML = """
myprojects:
  db:
    some-gitlab-repo:
      forge: gitlab
      url: https://gitlab.example.com/foss/some-gitlab-repo
  github:
    my-tool:
      forge: github
      url: https://github.com/mxmehl/my-tool
"""


def test_load_repos_filters_by_forge_and_derives_paths() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(FIXTURE_YAML)
        fixture_path = Path(f.name)

    try:
        repos = load_repos(fixture_path, forge="github")
        assert len(repos) == 1, f"expected 1 github repo, got {len(repos)}"
        repo = repos[0]
        assert repo.name == "my-tool"
        assert repo.owner == "mxmehl"
        assert repo.full_name == "mxmehl/my-tool"
        assert repo.local_path == Path("~/Git/github/my-tool").expanduser()

        all_repos = load_repos(fixture_path, forge=None)
        assert len(all_repos) == 2, f"expected 2 total repos, got {len(all_repos)}"
    finally:
        fixture_path.unlink()


def test_config_env_var_takes_precedence_over_file() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write('github_token = "file-token"\nmerge_method = "rebase"\n')
        config_path = Path(f.name)

    try:
        os.environ["GITHUB_TOKEN"] = "env-token"
        cfg = load_config(config_path)
        assert cfg.github_token == "env-token", "env var should win over config file"
        assert cfg.merge_method == "rebase", "file value should be used when no env override exists"
    finally:
        del os.environ["GITHUB_TOKEN"]
        config_path.unlink()


def test_config_defaults_when_no_file_and_no_env() -> None:
    os.environ.pop("GITHUB_TOKEN", None)
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.github_token is None
    assert cfg.merge_method == DEFAULT_MERGE_METHOD
    assert cfg.sort_by == DEFAULT_SORT_BY
    assert cfg.labels == DEFAULT_LABELS


if __name__ == "__main__":
    test_load_repos_filters_by_forge_and_derives_paths()
    test_config_env_var_takes_precedence_over_file()
    test_config_defaults_when_no_file_and_no_env()
    print("All task 1 checks passed.")
