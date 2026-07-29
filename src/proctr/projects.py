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

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_ROOT_PATH = Path("~/Git").expanduser()


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
        return urlparse(self.url).path.strip("/")

    @property
    def host(self) -> str:
        """Return the hostname of the repo's forge instance, e.g. 'gitlab.example.com'."""
        return urlparse(self.url).hostname or ""


def _owner_from_url(url: str) -> str:
    """Extract the owner/namespace (all path segments except the repo name) from a URL.

    For GitHub/Gitea this is a single segment (owner/repo). GitLab supports
    arbitrarily nested subgroups (group/subgroup/.../repo), so the owner
    must be everything up to the last segment, not just the first one.
    """
    parts = urlparse(url).path.strip("/").split("/")
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
