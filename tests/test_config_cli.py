"""Tests for `proctr config` helpers: myprojects.yaml generation and config.toml editing."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import tomllib
from pathlib import Path

import jsonschema
import pytest
import yaml

import proctr.config as config_module
from proctr.config_cli import _parse_value, generate_myprojects, set_config_value
from tests.test_projects import _init_repo


def _use_tmp_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect config_file_path() (used by both config.py and config_cli.py) into tmp_path."""
    monkeypatch.setattr(config_module, "user_config_dir", lambda _name: str(tmp_path))


def test_set_config_value_preserves_comments(tmp_path: Path) -> None:
    """Setting a plain key leaves other comments/keys in the file untouched."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('# a comment\nmerge_method = "squash"\nsort_by = "age"\n')

    set_config_value("merge_method", "rebase", path=config_path)

    text = config_path.read_text()
    assert "# a comment" in text
    assert 'sort_by = "age"' in text
    assert tomllib.loads(text)["merge_method"] == "rebase"


def test_set_config_value_quoted_dotted_key(tmp_path: Path) -> None:
    r"""A quoted host segment in the key path is handled correctly, e.g. gitlab."host".token."""
    config_path = tmp_path / "config.toml"

    set_config_value('gitlab."gitlab.example.com".token', "glpat-xxx", path=config_path)

    data = tomllib.loads(config_path.read_text())
    assert data["gitlab"]["gitlab.example.com"]["token"] == "glpat-xxx"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("squash", "squash"),
        ("true", True),
        ('["Renovate"]', ["Renovate"]),
    ],
)
def test_set_config_value_type_coercion(value: str, expected: object) -> None:
    """Bare words fall back to plain strings; valid TOML literals are parsed as such."""
    assert _parse_value(value) == expected


def test_set_config_value_rejects_invalid_schema(tmp_path: Path) -> None:
    """An unknown top-level key fails CONFIG_SCHEMA validation and nothing is written."""
    config_path = tmp_path / "config.toml"

    with pytest.raises(jsonschema.ValidationError):
        set_config_value("bogus_top_level_key", "x", path=config_path)

    assert not config_path.exists()


def test_generate_myprojects_known_hosts_need_no_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """github.com and gitlab.com repos are resolved without ever calling input()."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "gh" / "my-tool", url="https://github.com/mxmehl/my-tool")
    _init_repo(root_dir / "gl" / "other", url="https://gitlab.com/mxmehl/other")
    monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(AssertionError))

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    forges = {meta["forge"] for group in data["myprojects"].values() for meta in group.values()}
    assert forges == {"github", "gitlab"}


def test_generate_myprojects_unresolved_host_prompts_once_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unrecognized host is prompted for once, then remembered on a later invocation."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "work" / "internal", url="https://git.example.com/team/internal")

    answers = iter(["g", ""])  # gitlab, then accept the discovered host as canonical
    monkeypatch.setattr("builtins.input", lambda *_a: next(answers))
    target1 = tmp_path / "myprojects1.yaml"
    generate_myprojects(root_dir, target1)

    data = yaml.safe_load(target1.read_text())
    assert data["myprojects"]["work"]["internal"]["forge"] == "gitlab"
    config_data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert "git.example.com" in config_data["gitlab"]

    # Second invocation: the host is now known, input() must not be called again.
    monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(AssertionError))
    target2 = tmp_path / "myprojects2.yaml"
    generate_myprojects(root_dir, target2)
    data2 = yaml.safe_load(target2.read_text())
    assert data2["myprojects"]["work"]["internal"]["forge"] == "gitlab"


def test_generate_myprojects_unresolved_ssh_host_prompts_for_canonical_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An SSH-only discovered host can be mapped to a different canonical HTTPS host.

    Regression test: a discovered remote host like "ssh.git.example.com" must not
    be written verbatim as the myprojects.yaml URL host when the user provides a
    different real HTTPS/API host at the prompt.
    """
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(
        root_dir / "work" / "internal",
        url="git@ssh.git.example.com:team/internal.git",
    )

    answers = iter(["g", "git.example.com"])
    monkeypatch.setattr("builtins.input", lambda *_a: next(answers))
    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    entry = data["myprojects"]["work"]["internal"]
    assert entry["url"] == "https://git.example.com/team/internal"
    config_data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert config_data["gitlab"]["git.example.com"]["ssh_host"] == "ssh.git.example.com"


def test_generate_myprojects_skipped_host_excludes_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipping a host at the prompt excludes its repo(s) from the generated file."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "work" / "internal", url="https://git.example.com/team/internal")
    monkeypatch.setattr("builtins.input", lambda *_a: "s")

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    assert data["myprojects"] == {}
    assert not (tmp_path / "config.toml").exists()


def test_generate_myprojects_writes_https_url_for_scp_style_ssh_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo cloned over SSH still gets a browsable https:// URL in myprojects.yaml.

    Regression test: the raw `origin` remote (scp-like `user@host:path`) was
    previously stored verbatim, which isn't a URL a browser (or the "open
    issues" action) can use.
    """
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "gh" / "my-tool", url="git@github.com:mxmehl/my-tool.git")

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    assert data["myprojects"]["gh"]["my-tool"]["url"] == "https://github.com/mxmehl/my-tool"


def test_generate_myprojects_uses_configured_ssh_host_as_canonical_gitlab_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GitLab instance whose SSH host differs from its public host resolves to the public one.

    Regression test: e.g. `[gitlab."git.example.com"] ssh_host = "ssh.git.example.com"`
    means origin is cloned via the SSH-only host but the real public/API host
    (used for both the forge lookup and the generated URL) is the table key.
    """
    _use_tmp_config_dir(monkeypatch, tmp_path)
    (tmp_path / "config.toml").write_text(
        '[gitlab."git.example.com"]\nssh_host = "ssh.git.example.com"\n'
    )
    root_dir = tmp_path / "root"
    _init_repo(
        root_dir / "work" / "internal",
        url="git@ssh.git.example.com:team/internal.git",
    )
    monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(AssertionError))

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    entry = data["myprojects"]["work"]["internal"]
    assert entry["forge"] == "gitlab"
    assert entry["url"] == "https://git.example.com/team/internal"


def test_generate_myprojects_ssh_host_mapping_beats_stray_direct_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover empty `[gitlab."<ssh-host>"]` table doesn't shadow the ssh_host mapping.

    Regression test: an earlier run (before ssh_host was configured) may
    have added the SSH host as its own table via the interactive prompt.
    The ssh_host reverse-lookup must still win over that direct match, or
    the generated URL silently reverts to the unreachable SSH host.
    """
    _use_tmp_config_dir(monkeypatch, tmp_path)
    (tmp_path / "config.toml").write_text(
        '[gitlab."git.example.com"]\n'
        'ssh_host = "ssh.git.example.com"\n'
        "\n"
        '[gitlab."ssh.git.example.com"]\n'
    )
    root_dir = tmp_path / "root"
    _init_repo(
        root_dir / "work" / "internal",
        url="git@ssh.git.example.com:team/internal.git",
    )
    monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(AssertionError))

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    entry = data["myprojects"]["work"]["internal"]
    assert entry["url"] == "https://git.example.com/team/internal"


def test_generate_myprojects_refuses_existing_target_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing target file is left untouched unless force=True."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "gh" / "my-tool", url="https://github.com/mxmehl/my-tool")
    target = tmp_path / "myprojects.yaml"
    target.write_text("untouched: true\n")

    with pytest.raises(FileExistsError):
        generate_myprojects(root_dir, target)
    assert target.read_text() == "untouched: true\n"

    generate_myprojects(root_dir, target, force=True)
    assert "untouched" not in target.read_text()


def test_generate_myprojects_dedupes_name_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two repos with the same directory name in the same group get disambiguated."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "group" / "proj", url="https://github.com/mxmehl/proj-a")
    _init_repo(root_dir / "group" / "nested" / "proj", url="https://github.com/mxmehl/proj-b")

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    assert set(data["myprojects"]["group"]) == {"proj", "proj-2"}


def test_generate_myprojects_dedupes_same_remote_cloned_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two local clones of the same remote repo only produce one myprojects.yaml entry.

    Regression test: without this, fetch_all_prs would fetch and render
    that repo's PRs twice, crashing the TUI on a duplicate DataTable row
    key (real bug: `lizenzkompass` cloned into both ~/Git/db and
    ~/Git/scanoss-poc).
    """
    _use_tmp_config_dir(monkeypatch, tmp_path)
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "db" / "proj", url="https://github.com/mxmehl/proj")
    _init_repo(root_dir / "other" / "proj", url="https://github.com/mxmehl/proj")

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    all_entries = [meta for group in data["myprojects"].values() for meta in group.values()]
    assert len(all_entries) == 1
    assert all_entries[0]["url"] == "https://github.com/mxmehl/proj"


def test_generate_myprojects_renders_home_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo under the user's home directory gets a ~/-relative path in the output."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    root_dir = tmp_path / "root"
    _init_repo(root_dir / "gh" / "my-tool", url="https://github.com/mxmehl/my-tool")

    target = tmp_path / "myprojects.yaml"
    generate_myprojects(root_dir, target)

    data = yaml.safe_load(target.read_text())
    assert data["myprojects"]["gh"]["my-tool"]["path"] == "~/root/gh/my-tool"
