"""Tests for the per-repo forge dispatch logic."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import re
from pathlib import Path

import pytest

from lsrenovate.app import ForgeDispatcher
from lsrenovate.config import Config, GiteaInstanceConfig, GitHubConfig, GitLabInstanceConfig
from lsrenovate.forges.gitea import GiteaForge
from lsrenovate.forges.github import GitHubForge
from lsrenovate.forges.gitlab import GitLabForge
from lsrenovate.projects import Repo


def _repo(forge: str, host: str, name: str = "my-tool") -> Repo:
    return Repo(
        group="grp",
        name=name,
        forge=forge,
        url=f"https://{host}/owner/{name}",
        owner="owner",
        local_path=Path(f"~/Git/grp/{name}").expanduser(),
    )


def _config(**overrides: object) -> Config:
    defaults = {
        "github": GitHubConfig(token=None),
        "merge_method": "squash",
        "myprojects_path": Path("/dev/null"),
        "sort_by": "repo",
        "labels": ["Renovate"],
        "gitlab_instances": {},
        "gitea_instances": {},
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def test_dispatcher_resolves_github() -> None:
    """A github repo always resolves to a GitHubForge, no per-instance config needed."""
    dispatcher = ForgeDispatcher(_config(github=GitHubConfig(token="ghp_x")))
    forge = dispatcher(_repo("github", "github.com"))
    assert isinstance(forge, GitHubForge)


def test_dispatcher_resolves_gitlab_with_matching_instance() -> None:
    """A gitlab repo resolves using the [gitlab."<host>"] config for its host."""
    config = _config(gitlab_instances={"gitlab.example.com": GitLabInstanceConfig(token="glpat-x")})
    dispatcher = ForgeDispatcher(config)
    forge = dispatcher(_repo("gitlab", "gitlab.example.com"))
    assert isinstance(forge, GitLabForge)


def test_dispatcher_raises_for_gitlab_host_without_config() -> None:
    """A gitlab repo whose host has no matching config table raises a clear error."""
    dispatcher = ForgeDispatcher(_config())
    with pytest.raises(ValueError, match=re.escape("gitlab.example.com")):
        dispatcher(_repo("gitlab", "gitlab.example.com"))


def test_dispatcher_resolves_gitea_with_matching_instance() -> None:
    """A gitea repo resolves using the [gitea."<host>"] config for its host."""
    config = _config(gitea_instances={"gitea.example.com": GiteaInstanceConfig(login="my-login")})
    dispatcher = ForgeDispatcher(config)
    forge = dispatcher(_repo("gitea", "gitea.example.com"))
    assert isinstance(forge, GiteaForge)


def test_dispatcher_raises_for_gitea_host_without_config() -> None:
    """A gitea repo whose host has no matching config table raises a clear error."""
    dispatcher = ForgeDispatcher(_config())
    with pytest.raises(ValueError, match=re.escape("gitea.example.com")):
        dispatcher(_repo("gitea", "gitea.example.com"))


def test_dispatcher_raises_for_unsupported_forge() -> None:
    """An unrecognized forge name raises a clear error rather than dispatching silently."""
    dispatcher = ForgeDispatcher(_config())
    with pytest.raises(ValueError, match="Unsupported forge"):
        dispatcher(_repo("bitbucket", "bitbucket.org"))


def test_dispatcher_caches_instances_by_forge_and_host() -> None:
    """Two repos on the same gitlab host reuse the same GitLabForge instance."""
    config = _config(gitlab_instances={"gitlab.example.com": GitLabInstanceConfig(token="x")})
    dispatcher = ForgeDispatcher(config)

    forge_a = dispatcher(_repo("gitlab", "gitlab.example.com", name="repo-a"))
    forge_b = dispatcher(_repo("gitlab", "gitlab.example.com", name="repo-b"))

    assert forge_a is forge_b


def test_dispatcher_builds_separate_instances_for_different_hosts() -> None:
    """Two different gitlab hosts each get their own GitLabForge instance."""
    config = _config(
        gitlab_instances={
            "gitlab-a.example.com": GitLabInstanceConfig(token="a"),
            "gitlab-b.example.com": GitLabInstanceConfig(token="b"),
        }
    )
    dispatcher = ForgeDispatcher(config)

    forge_a = dispatcher(_repo("gitlab", "gitlab-a.example.com"))
    forge_b = dispatcher(_repo("gitlab", "gitlab-b.example.com"))

    assert forge_a is not forge_b


def test_dispatcher_uses_api_host_override_for_gitlab_env() -> None:
    """When api_host is configured, GitLabForge is built with that host, not the URL host."""
    config = _config(
        gitlab_instances={
            "gitlab.example.com": GitLabInstanceConfig(token="x", api_host="ssh.gitlab.example.com")
        }
    )
    dispatcher = ForgeDispatcher(config)

    forge = dispatcher(_repo("gitlab", "gitlab.example.com"))

    assert forge._env()["GITLAB_HOST"] == "ssh.gitlab.example.com"  # noqa: SLF001


def test_dispatcher_uses_per_instance_labels_over_global_default() -> None:
    """A GitLab instance with its own labels uses those instead of the global default."""
    config = _config(
        labels=["Renovate"],
        gitlab_instances={
            "gitlab.example.com": GitLabInstanceConfig(token="x", labels=["dependencies"])
        },
    )
    dispatcher = ForgeDispatcher(config)

    forge = dispatcher(_repo("gitlab", "gitlab.example.com"))

    assert forge._labels == ["dependencies"]  # noqa: SLF001


def test_dispatcher_falls_back_to_global_labels_when_instance_labels_unset() -> None:
    """A GitLab instance with no labels configured falls back to the global default."""
    config = _config(
        labels=["Renovate"],
        gitlab_instances={"gitlab.example.com": GitLabInstanceConfig(token="x")},
    )
    dispatcher = ForgeDispatcher(config)

    forge = dispatcher(_repo("gitlab", "gitlab.example.com"))

    assert forge._labels == ["Renovate"]  # noqa: SLF001
