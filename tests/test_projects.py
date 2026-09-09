"""Tests for myprojects.yaml parsing."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import subprocess
from pathlib import Path

from proctr.projects import load_repos, walk_git_repos

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


def _init_repo(path: Path, *, url: str | None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)  # noqa: S607
    if url is not None:
        subprocess.run(  # noqa: S603
            ["git", "remote", "add", "origin", url],  # noqa: S607
            cwd=path,
            check=True,
        )


def test_walk_git_repos_finds_repo_and_reads_origin(tmp_path: Path) -> None:
    """A git repo with an origin remote is found, with its path/url/host recorded."""
    repo_path = tmp_path / "github" / "my-tool"
    _init_repo(repo_path, url="https://github.com/mxmehl/my-tool")

    repos, skipped = walk_git_repos(tmp_path)

    assert skipped == []
    assert len(repos) == 1
    assert repos[0].path == repo_path
    assert repos[0].url == "https://github.com/mxmehl/my-tool"
    assert repos[0].host == "github.com"


def test_walk_git_repos_skips_repo_with_no_origin(tmp_path: Path) -> None:
    """A git repo with no origin remote is recorded as skipped, not returned as a repo."""
    repo_path = tmp_path / "scratch"
    _init_repo(repo_path, url=None)

    repos, skipped = walk_git_repos(tmp_path)

    assert repos == []
    assert skipped == [repo_path]


def test_walk_git_repos_does_not_descend_into_found_repo(tmp_path: Path) -> None:
    """A nested .git (e.g. a submodule) inside an already-found repo is not walked into."""
    repo_path = tmp_path / "outer"
    _init_repo(repo_path, url="https://github.com/mxmehl/outer")
    _init_repo(repo_path / "vendor" / "nested", url="https://github.com/mxmehl/nested")

    repos, skipped = walk_git_repos(tmp_path)

    assert skipped == []
    assert len(repos) == 1
    assert repos[0].path == repo_path


def test_walk_git_repos_parses_scp_style_ssh_remote(tmp_path: Path) -> None:
    """A scp-like SSH remote (user@host:path, no scheme) resolves a real host, not "".

    Regression test: `urlparse` can't parse this shorthand and silently
    returns an empty hostname, which made every such repo look like an
    "unrecognized host ''" during myprojects.yaml generation.
    """
    repo_path = tmp_path / "self-hosted" / "my-tool"
    _init_repo(repo_path, url="git@src.example.com:mxmehl/my-tool.git")

    repos, skipped = walk_git_repos(tmp_path)

    assert skipped == []
    assert len(repos) == 1
    assert repos[0].host == "src.example.com"


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


def test_repo_host_and_full_name_parse_scp_style_url(tmp_path: Path) -> None:
    """Repo.host/full_name parse scp-like SSH URLs the same way walk_git_repos does."""
    fixture_path = tmp_path / "myprojects.yaml"
    fixture_path.write_text(
        "myprojects:\n"
        "  self-hosted:\n"
        "    my-tool:\n"
        "      forge: gitea\n"
        "      url: git@src.example.com:mxmehl/my-tool.git\n"
    )

    repos = load_repos(fixture_path, forge="gitea")

    assert len(repos) == 1
    assert repos[0].host == "src.example.com"
    assert repos[0].full_name == "mxmehl/my-tool"
