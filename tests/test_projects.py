"""Tests for myprojects.yaml parsing."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from pathlib import Path

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


def test_load_repos_filters_by_forge_and_derives_paths(tmp_path: Path) -> None:
    """Filtering by forge="github" returns only the matching repo with derived fields."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(FIXTURE_YAML)

    repos = load_repos(fixture_path, forge="github")

    assert len(repos) == 1
    repo = repos[0]
    assert repo.name == "my-tool"
    assert repo.owner == "mxmehl"
    assert repo.full_name == "mxmehl/my-tool"
    assert repo.local_path == Path("~/Git/github/my-tool").expanduser()


def test_load_repos_forge_none_returns_all(tmp_path: Path) -> None:
    """Passing forge=None returns repos across all forges."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(FIXTURE_YAML)

    all_repos = load_repos(fixture_path, forge=None)

    assert len(all_repos) == 2
