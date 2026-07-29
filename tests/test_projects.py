"""Tests for myprojects.yaml parsing."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from pathlib import Path

from proctr.projects import load_repos

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


def test_load_repos_derives_owner_for_gitlab_nested_subgroups(tmp_path: Path) -> None:
    """A nested GitLab subgroup URL derives the full path as owner, not just the first segment."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(
        "myprojects:\n"
        "  work:\n"
        "    hugo-theme:\n"
        "      forge: gitlab\n"
        "      url: https://gitlab.example.com/group/subgroup/community/hugo-theme\n"
    )

    repos = load_repos(fixture_path, forge="gitlab")

    assert len(repos) == 1
    repo = repos[0]
    assert repo.owner == "group/subgroup/community"
    assert repo.full_name == "group/subgroup/community/hugo-theme"


def test_load_repos_path_overrides_local_path_convention(tmp_path: Path) -> None:
    """An explicit `path` key overrides the ~/Git/<group>/<project> convention."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(
        "myprojects:\n"
        "  github:\n"
        "    my-tool:\n"
        "      forge: github\n"
        "      url: https://github.com/mxmehl/my-tool\n"
        "      path: ~/code/my-tool\n"
    )

    repos = load_repos(fixture_path, forge="github")

    assert len(repos) == 1
    assert repos[0].local_path == Path("~/code/my-tool").expanduser()


def test_load_repos_root_path_overrides_default(tmp_path: Path) -> None:
    """A top-level `root_path` key overrides the default ~/Git clone root."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(
        "root_path: ~/Code\n"
        "myprojects:\n"
        "  github:\n"
        "    my-tool:\n"
        "      forge: github\n"
        "      url: https://github.com/mxmehl/my-tool\n"
    )

    repos = load_repos(fixture_path, forge="github")

    assert len(repos) == 1
    assert repos[0].local_path == Path("~/Code/github/my-tool").expanduser()


def test_full_name_uses_url_slug_not_yaml_key_when_they_differ(tmp_path: Path) -> None:
    """full_name must reflect the URL's real repo slug even if the myprojects.yaml key differs.

    Regression test: myprojects.yaml keys are a local naming convention and
    may not match the forge's actual project path (e.g. a local key of
    "foss-renovate" pointing at a real GitLab project path of
    "foss/renovate"). Using the yaml key for API calls would 404.
    """
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(
        "myprojects:\n"
        "  db:\n"
        "    foss-renovate:\n"
        "      forge: gitlab\n"
        "      url: https://git.tech.rz.db.de/foss/renovate\n"
    )

    repos = load_repos(fixture_path, forge="gitlab")

    assert len(repos) == 1
    repo = repos[0]
    assert repo.name == "foss-renovate"  # yaml key, used for local_path only
    assert repo.full_name == "foss/renovate"  # real URL slug, used for API calls
    assert repo.local_path == Path("~/Git/db/foss-renovate").expanduser()
