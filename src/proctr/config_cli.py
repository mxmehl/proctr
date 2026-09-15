"""CLI helpers for `proctr config`: myprojects.yaml generation and config.toml editing.

Both subcommands share the same tomlkit-backed read-modify-write helpers
so config.toml's existing comments/formatting survive every edit, and
every write is validated against CONFIG_SCHEMA before it lands on disk.
"""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema
import tomlkit
import yaml

from proctr.config import CONFIG_SCHEMA, config_file_path, load_config
from proctr.projects import parse_git_remote, walk_git_repos

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proctr.config import Config
    from proctr.projects import DiscoveredRepo

# Resolved without asking or touching config.toml; credentials (if any) for
# these hosts are still whatever the user configures separately, same as
# any other forge host.
KNOWN_HOSTS = {"github.com": "github", "gist.github.com": "github", "gitlab.com": "gitlab"}


def _load_toml_document(path: Path) -> tomlkit.TOMLDocument:
    """Parse config.toml (preserving comments/formatting), or an empty document if missing."""
    if path.is_file():
        return tomlkit.parse(path.read_text())
    return tomlkit.document()


def _validate_and_write(path: Path, doc: tomlkit.TOMLDocument) -> None:
    """Validate doc against CONFIG_SCHEMA, then write it — never leaves a broken file on disk."""
    text = tomlkit.dumps(doc)
    jsonschema.validate(instance=tomllib.loads(text), schema=CONFIG_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _parse_key_path(key: str) -> list[str]:
    """Parse a dotted/quoted TOML key path, e.g. `gitlab."gitlab.example.com".token`.

    Reuses tomllib's own dotted-key grammar (by parsing `key = true`) so
    quoted segments (hostnames containing dots) are handled for free,
    without hand-rolled key parsing.
    """
    try:
        parsed: object = tomllib.loads(f"{key} = true")
    except tomllib.TOMLDecodeError as exc:
        msg = f"Invalid key {key!r}: {exc}"
        raise ValueError(msg) from exc

    segments: list[str] = []
    node = parsed
    while isinstance(node, dict):
        if len(node) != 1:
            msg = f"Invalid key {key!r}: must be a single dotted path"
            raise ValueError(msg)
        segment, node = next(iter(node.items()))
        segments.append(segment)
    return segments


def _parse_value(value: str) -> object:
    """Parse value as a TOML literal (bool/int/list/quoted string); fall back to a plain string.

    This lets `merge_method squash` work without quoting, while still
    supporting e.g. `labels '["Renovate"]'` when a real TOML value is needed.
    """
    try:
        return tomllib.loads(f"v = {value}")["v"]
    except tomllib.TOMLDecodeError:
        return value


def _set_nested(doc: tomlkit.TOMLDocument, key_path: list[str], value: object) -> None:
    """Set value at key_path in doc, creating intermediate tables as needed."""
    node = doc
    for segment in key_path[:-1]:
        existing = node.get(segment)
        if existing is None:
            existing = tomlkit.table()
            node[segment] = existing
        node = existing
    node[key_path[-1]] = value


def set_config_value(key: str, value: str, *, path: Path | None = None) -> None:
    """Set a single config.toml value at a dotted key path, preserving the rest of the file."""
    path = path or config_file_path()
    key_path = _parse_key_path(key)
    parsed_value = _parse_value(value)
    doc = _load_toml_document(path)
    _set_nested(doc, key_path, parsed_value)
    _validate_and_write(path, doc)


def _add_forge_instance(
    host: str, kind: str, *, ssh_host: str | None = None, path: Path | None = None
) -> None:
    """Persist a [gitlab."host"]/[gitea."host"] table so future runs recognize the host.

    ssh_host (gitlab only) is set when the canonical HTTPS host differs
    from the host actually discovered on the scanned repo's `origin`
    remote, so later scans of the same SSH-only remote resolve back to
    this table instead of prompting again.
    """
    path = path or config_file_path()
    doc = _load_toml_document(path)
    table = doc.get(kind)
    if table is None:
        table = tomlkit.table()
        doc[kind] = table
    instance_table = tomlkit.table()
    if ssh_host:
        instance_table["ssh_host"] = ssh_host
    table[host] = instance_table
    _validate_and_write(path, doc)


def _resolve_forge(host: str, config: Config) -> tuple[str, str] | None:
    """Resolve a scanned repo host to (forge, canonical_host), or None if unresolved.

    canonical_host is the public HTTPS/API host used to build the
    https:// URL; it's usually just `host` itself, except for a GitLab
    instance configured with `ssh_host` pointing at a different SSH-only
    hostname than the table's own key (see GitLabInstanceConfig
    docstring) — there, the table key is the canonical public host, not
    the SSH host origin uses. The ssh_host match is checked before a
    direct table-key match so a stray leftover `[gitlab."<ssh-host>"]`
    table (e.g. from before ssh_host was configured) can't shadow it.
    """
    if host in KNOWN_HOSTS:
        return KNOWN_HOSTS[host], host
    for gitlab_host, instance in config.gitlab_instances.items():
        if instance.ssh_host == host:
            return "gitlab", gitlab_host
    if host in config.gitlab_instances:
        return "gitlab", host
    if host in config.gitea_instances:
        return "gitea", host
    return None


def _group_for(path: Path, root_dir: Path) -> str:
    """Return the top-level directory segment under root_dir, or "root" for root_dir itself."""
    relative = path.relative_to(root_dir)
    return relative.parts[0] if relative.parts else "root"


def _unique_name(group: Mapping[str, object], name: str) -> str:
    """Disambiguate a name already used within the same group by appending -2, -3, ..."""
    if name not in group:
        return name
    suffix = 2
    while f"{name}-{suffix}" in group:
        suffix += 1
    return f"{name}-{suffix}"


def _display_path(path: Path) -> str:
    """Render path home-relative (~/...) when possible, for a portable/readable myprojects.yaml."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _https_url(repo: DiscoveredRepo, canonical_host: str) -> str:
    """Build the public https:// URL for a scanned repo (git remotes are often SSH)."""
    return f"https://{canonical_host}/{parse_git_remote(repo.url)[1]}"


def generate_myprojects(root_dir: Path, target: Path, *, force: bool = False) -> None:
    """Scan root_dir for git repos and write a fresh myprojects.yaml to target.

    Refuses to touch an existing target unless force=True. Unrecognized
    remote hosts (anything but github.com/gitlab.com or an already
    configured GitLab/Gitea host) are resolved interactively, once each,
    and persisted to config.toml immediately — so a later invocation (or
    the running TUI) never asks about that host again.
    """
    if target.exists() and not force:
        msg = f"{target} already exists; pass --force to overwrite"
        raise FileExistsError(msg)

    repos, skipped_paths = walk_git_repos(root_dir)
    config = load_config()

    entries, unresolved_repos = _split_by_resolvable(repos, config)
    new_entries, skipped_hosts = _resolve_interactively(unresolved_repos)
    entries.extend(new_entries)

    myprojects, duplicate_paths = _build_myprojects(entries, root_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump({"myprojects": myprojects}, sort_keys=False))

    _print_summary(len(entries) - len(duplicate_paths), target, skipped_paths, skipped_hosts)
    _print_duplicates(duplicate_paths)


def _split_by_resolvable(
    repos: list[DiscoveredRepo], config: Config
) -> tuple[list[tuple[DiscoveredRepo, str, str]], list[DiscoveredRepo]]:
    """Split repos into (forge-resolved entries, repos needing interactive resolution)."""
    resolved_hosts: dict[str, tuple[str, str]] = {}
    entries: list[tuple[DiscoveredRepo, str, str]] = []
    unresolved_repos: list[DiscoveredRepo] = []
    for repo in repos:
        resolved = resolved_hosts.get(repo.host) or _resolve_forge(repo.host, config)
        if resolved is None:
            unresolved_repos.append(repo)
            continue
        resolved_hosts[repo.host] = resolved
        forge, canonical_host = resolved
        entries.append((repo, forge, canonical_host))
    return entries, unresolved_repos


def _resolve_interactively(
    unresolved_repos: list[DiscoveredRepo],
) -> tuple[list[tuple[DiscoveredRepo, str, str]], list[str]]:
    """Prompt once per unresolved host, persisting each decision to config.toml immediately.

    For GitLab, also asks for the canonical HTTPS/API host, since the
    discovered host is often an SSH-only hostname that differs from the
    real API host (e.g. "ssh.gitlab.example.com" vs "gitlab.example.com").
    Pressing Enter accepts the discovered host as-is (no ssh_host needed);
    typing a different host persists it as ssh_host on the new table, and
    that host becomes canonical_host for the URL below.

    Returns (newly resolved entries, hosts the user chose to skip).
    """
    resolved: dict[str, tuple[str, str]] = {}
    skipped_hosts: list[str] = []
    for host in sorted({repo.host for repo in unresolved_repos}):
        answer = input(f"Unrecognized host '{host}': (g)itlab, (t)ea/gitea, or (s)kip? ")
        answer = answer.strip().lower()
        if answer in ("g", "gitlab"):
            canonical_host = input(f"  HTTPS/API host for '{host}' [{host}]: ").strip() or host
            ssh_host = host if canonical_host != host else None
            _add_forge_instance(canonical_host, "gitlab", ssh_host=ssh_host)
            resolved[host] = ("gitlab", canonical_host)
        elif answer in ("t", "tea", "gitea"):
            _add_forge_instance(host, "gitea")
            resolved[host] = ("gitea", host)
        else:
            skipped_hosts.append(host)

    entries = [(repo, *resolved[repo.host]) for repo in unresolved_repos if repo.host in resolved]
    return entries, skipped_hosts


def _build_myprojects(
    entries: list[tuple[DiscoveredRepo, str, str]], root_dir: Path
) -> tuple[dict[str, dict[str, dict[str, str]]], list[Path]]:
    """Build the nested myprojects.yaml dict from resolved (repo, forge, canonical_host) entries.

    Two locally-scanned repo directories can point at the same remote
    project (e.g. cloned twice into different local paths) — proctr only
    needs to track that project once, since duplicate entries would make
    fetch_all_prs list and render its PRs twice (crashing the TUI on a
    duplicate DataTable row key). Dedup by the resolved (forge,
    canonical_host, full_name) identity — the same thing the forge API
    itself would see as "the same repo" — keeping the first occurrence
    found (stable, since os.walk order is deterministic) and returning
    the paths of the ones dropped for the caller to report.
    """
    myprojects: dict[str, dict[str, dict[str, str]]] = {}
    seen_urls: set[tuple[str, str, str]] = set()
    duplicate_paths: list[Path] = []
    for repo, forge, canonical_host in entries:
        full_name = parse_git_remote(repo.url)[1]
        identity = (forge, canonical_host, full_name)
        if identity in seen_urls:
            duplicate_paths.append(repo.path)
            continue
        seen_urls.add(identity)

        group = _group_for(repo.path, root_dir)
        name = _unique_name(myprojects.setdefault(group, {}), repo.path.name)
        myprojects[group][name] = {
            "forge": forge,
            "url": _https_url(repo, canonical_host),
            "path": _display_path(repo.path),
        }
    return myprojects, duplicate_paths


def _print_summary(
    written: int, target: Path, skipped_paths: list[Path], skipped_hosts: list[str]
) -> None:
    """Print a short summary of what generate_myprojects wrote and skipped."""
    print(f"Wrote {written} repo(s) to {target}")
    if skipped_paths:
        print(f"Skipped {len(skipped_paths)} repo(s) with no 'origin' remote:")
        for path in skipped_paths:
            print(f"  {path}")
    if skipped_hosts:
        print(f"Skipped host(s) (rerun to configure): {', '.join(skipped_hosts)}")


def _print_duplicates(duplicate_paths: list[Path]) -> None:
    """Print the local paths dropped because another scanned path has the same remote repo."""
    if duplicate_paths:
        print(f"Skipped {len(duplicate_paths)} duplicate clone(s) of an already-added repo:")
        for path in duplicate_paths:
            print(f"  {path}")
