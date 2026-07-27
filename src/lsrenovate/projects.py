"""Parsing of myprojects.yaml into Repo records.

Local clone path convention: ~/Git/<group>/<project>, where <group> is the
top-level key under `myprojects` in the YAML file (not derived from the
repo URL's host).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

GIT_ROOT = Path("~/Git").expanduser()


@dataclass(frozen=True)
class Repo:
    """A single repository entry derived from myprojects.yaml."""

    group: str
    name: str
    forge: str
    url: str
    owner: str
    local_path: Path

    @property
    def full_name(self) -> str:
        """Return the "owner/repo" identifier used by gh."""
        return f"{self.owner}/{self.name}"


def _owner_from_url(url: str) -> str:
    """Extract the owner (first path segment) from a repo URL."""
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts else ""


def load_repos(myprojects_path: Path, *, forge: str | None = "github") -> list[Repo]:
    """Load repos from myprojects.yaml, optionally filtered by forge.

    Pass forge=None to return repos for all forges.
    """
    data = yaml.safe_load(myprojects_path.read_text())
    groups = data.get("myprojects", {})

    repos: list[Repo] = []
    for group, projects in groups.items():
        for name, meta in projects.items():
            repo_forge = meta.get("forge", "")
            if forge is not None and repo_forge != forge:
                continue
            url = meta.get("url", "")
            repos.append(
                Repo(
                    group=group,
                    name=name,
                    forge=repo_forge,
                    url=url,
                    owner=_owner_from_url(url),
                    local_path=GIT_ROOT / group / name,
                )
            )
    return repos
