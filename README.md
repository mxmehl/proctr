<!--
  SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>
  SPDX-License-Identifier: CC0-1.0
-->

# lsrenovate

[![Test suites](https://github.com/mxmehl/lsrenovate/actions/workflows/test.yaml/badge.svg)](https://github.com/mxmehl/lsrenovate/actions/workflows/test.yaml)
[![REUSE status](https://api.reuse.software/badge/github.com/mxmehl/lsrenovate)](https://api.reuse.software/info/github.com/mxmehl/lsrenovate)
[![The latest version can be found on PyPI.](https://img.shields.io/pypi/v/lsrenovate.svg)](https://pypi.org/project/lsrenovate/)
[![Information on what versions of Python are supported can be found on PyPI.](https://img.shields.io/pypi/pyversions/lsrenovate.svg)](https://pypi.org/project/lsrenovate/)

lsrenovate is a terminal UI for triaging open Renovate pull requests across many GitHub repositories at once. It reads a simple YAML project registry, fetches matching PRs concurrently via the `gh` CLI, and lets you review, merge, and jump into repos without leaving the terminal.

## Features

- **Cross-repo overview** — one table showing every open Renovate (or custom-labeled) PR across all your GitHub repos, with age, mergeable state, and merge readiness color-coded at a glance.
- **Multi-select merge** — tick PRs with `space` and merge them all with `m`; failures don't block the rest, and you get a summary afterward.
- **Jump to context** — open a PR in your browser (`o`) or drop into a shell at its local checkout (`s`), with your GitHub token already exported into the shell environment.
- **Configurable** — merge method, detection labels, sort order, and the project registry path are all overridable via a TOML config file.
- **Concurrent fetching** — all repos are queried in parallel via a thread pool, so refreshing dozens of repos takes seconds, not minutes.

## Requirements

- Python 3.12+
- [GitHub CLI (`gh`)](https://cli.github.com/), authenticated or provided a token via config/env (see below)

## Installation

### From PyPI

```sh
pip install lsrenovate
```

### From source

```sh
git clone https://github.com/mxmehl/lsrenovate.git
cd lsrenovate
uv sync --no-dev
```

## Quick start

1. **Create a project registry** — a YAML file listing the repos to monitor:

   ```yaml
   myprojects:
     github:
       my-tool:
         forge: github
         url: https://github.com/myuser/my-tool
   ```

   Repos are grouped by an arbitrary top-level key (e.g. `github`, `work`); this key also determines the local checkout path convention `~/Git/<group>/<project>`, used by the "open shell" action. Only entries with `forge: github` are used.

2. **Provide a GitHub token**, in order of precedence:
   - `GITHUB_TOKEN` environment variable, or
   - `github_token_command` in the config file — a command that prints the token to stdout, e.g. a password manager CLI, or
   - `github_token` in the config file (plaintext), or
   - fall back to `gh`'s own stored authentication.

3. **Run it:**

   ```sh
   lsrenovate
   ```

## Configuration

lsrenovate reads an optional TOML config file at your platform's user config directory (e.g. `~/Library/Application Support/lsrenovate/config.toml` on macOS, `~/.config/lsrenovate/config.toml` on Linux):

```toml
github_token = "ghp_..."               # optional; env var GITHUB_TOKEN takes precedence
github_token_command = ["kpxc_get_password", "cli://token-gh-cli"]  # optional; takes precedence over github_token
merge_method = "squash"                # "squash" (default), "merge", or "rebase"
labels = ["Renovate"]                  # PR label(s) to filter on; all must match
sort_by = "repo"                       # "repo" (default), "age", or "title"
myprojects_path = "~/path/to/myprojects.yaml"  # defaults to a file next to this config
```

`github_token_command` is run directly via subprocess (no shell involved, so it works the same regardless of your login shell), and its stdout (trimmed) is used as the token. This avoids storing a plaintext token in the config file. If the command fails, lsrenovate falls back to `github_token` (or `gh`'s own auth) and shows a warning on startup.

## Keybindings

| Key     | Action                                                |
| ------- | ------------------------------------------------------ |
| `space` | Toggle selection of the row under the cursor            |
| `m`     | Merge selected PRs (or the focused one if none selected) |
| `o`     | Open selected PRs (or the focused one) in the browser   |
| `s`     | Open a shell at the focused PR's local repo checkout    |
| `t`     | Cycle sort order (repo → age → title)                   |
| `r`     | Refresh the PR list                                     |
| `q`     | Quit                                                    |

## Copyright and Licensing

This project is licensed under the Apache License 2.0, copyrighted by Max Mehl. As the project follows the [REUSE](https://reuse.software) best practices, you can find licensing information for each individual file in the [LICENSES](LICENSES) directory or corresponding file headers.
