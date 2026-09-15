"""Parsing of myprojects.yaml into Repo records.

Local clone path convention: <root_path>/<group>/<project>, where <group>
and <project> are the top-level/second-level keys under `myprojects` in
the YAML file — these are a local naming convention and may differ from
the repo's actual slug on the forge, which is always derived from the
URL. `root_path` is an optional top-level key in the YAML file (sibling
of `myprojects`), defaulting to ~/Git. A project entry may set an
optional `path` key to override this convention with an explicit local
clone path instead.
"""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_ROOT_PATH = Path("~/Git").expanduser()
GIT_EXECUTABLE = shutil.which("git") or "git"


def parse_git_remote(url: str) -> tuple[str, str]:
    """Parse a git remote URL into (host, path), stripping a trailing `.git`.

    Handles both real URLs (https://, ssh://, ...) and the scp-like SSH
    shorthand `[user@]host:path` that `git remote get-url` commonly returns
    and that `urlparse` cannot parse (it yields an empty hostname/path).
    """
    if "://" in url:
        parsed = urlparse(url)
        host, path = parsed.hostname or "", parsed.path.strip("/")
    else:
        host, _, path = url.rpartition("@")[2].partition(":")
    return host, path.removesuffix(".git")


@dataclass(frozen=True)
class Repo:
    """A single repository entry derived from myprojects.yaml.

    `name` is the local key from myprojects.yaml (used only for
    local_path); `owner` and the repo slug used in `full_name` are always
    derived from the URL, since the local key is just a naming
    convention and may not match the forge's actual project path.
    """

    group: str
    name: str
    forge: str
    url: str
    owner: str
    local_path: Path

    @property
    def full_name(self) -> str:
        """Return the "owner/repo" (or GitLab "group/subgroup/.../repo") API identifier."""
        return parse_git_remote(self.url)[1]

    @property
    def host(self) -> str:
        """Return the hostname of the repo's forge instance, e.g. 'gitlab.example.com'."""
        return parse_git_remote(self.url)[0]


def _owner_from_url(url: str) -> str:
    """Extract the owner/namespace (all path segments except the repo name) from a URL.

    For GitHub/Gitea this is a single segment (owner/repo). GitLab supports
    arbitrarily nested subgroups (group/subgroup/.../repo), so the owner
    must be everything up to the last segment, not just the first one.
    """
    parts = parse_git_remote(url)[1].split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def load_repos(myprojects_path: Path, *, forge: str | None = None) -> list[Repo]:
    """Load repos from myprojects.yaml, optionally filtered by forge.

    Pass forge=None (the default) to return repos for all forges.
    """
    data = yaml.safe_load(myprojects_path.read_text())
    groups = data.get("myprojects", {})
    root_path = Path(data.get("root_path", DEFAULT_ROOT_PATH)).expanduser()

    repos: list[Repo] = []
    for group, projects in groups.items():
        for name, meta in projects.items():
            repo_forge = meta.get("forge", "")
            if forge is not None and repo_forge != forge:
                continue
            url = meta.get("url", "")
            path = meta.get("path")
            local_path = Path(path).expanduser() if path else root_path / group / name
            repos.append(
                Repo(
                    group=group,
                    name=name,
                    forge=repo_forge,
                    url=url,
                    owner=_owner_from_url(url),
                    local_path=local_path,
                )
            )
    return repos


@dataclass(frozen=True)
class DiscoveredRepo:
    """A git repo found on disk by `walk_git_repos`, before forge resolution."""

    path: Path
    url: str
    host: str


def walk_git_repos(root_dir: Path) -> tuple[list[DiscoveredRepo], list[Path]]:
    """Find git repos under root_dir and read each one's `origin` remote URL.

    Stops descending into a directory as soon as it's identified as a repo
    (no nested/vendored/submodule repos), so a `ponytail:` tradeoff applies
    the other way too: a branch that never contains a `.git` is walked in
    full, with no vendor/node_modules-style pruning beyond that.
    Returns (repos, skipped_paths), where skipped_paths are repos with no
    `origin` remote configured (or where `git` itself failed).
    """
    repos: list[DiscoveredRepo] = []
    skipped_paths: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root_dir, followlinks=False):
        path = Path(dirpath)
        if not (path / ".git").exists():
            continue
        dirnames[:] = []  # don't descend into a repo's own subdirectories
        result = subprocess.run(  # noqa: S603
            [GIT_EXECUTABLE, "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        url = result.stdout.strip()
        if result.returncode != 0 or not url:
            skipped_paths.append(path)
            continue
        repos.append(DiscoveredRepo(path=path, url=url, host=parse_git_remote(url)[0]))
    return repos, skipped_paths
