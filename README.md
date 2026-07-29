<!--
  SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>
  SPDX-License-Identifier: CC0-1.0
-->

# lsrenovate

[![Test suites](https://github.com/mxmehl/lsrenovate/actions/workflows/test.yaml/badge.svg)](https://github.com/mxmehl/lsrenovate/actions/workflows/test.yaml)
[![REUSE status](https://api.reuse.software/badge/github.com/mxmehl/lsrenovate)](https://api.reuse.software/info/github.com/mxmehl/lsrenovate)
[![The latest version can be found on PyPI.](https://img.shields.io/pypi/v/lsrenovate.svg)](https://pypi.org/project/lsrenovate/)
[![Information on what versions of Python are supported can be found on PyPI.](https://img.shields.io/pypi/pyversions/lsrenovate.svg)](https://pypi.org/project/lsrenovate/)

lsrenovate is a terminal UI for triaging open Renovate pull requests across many GitHub, GitLab, and Gitea repositories at once. It reads a simple YAML project registry, fetches matching PRs/MRs concurrently, and lets you review, merge, and jump into repos without leaving the terminal.

## Columns

The table shows a few independent signals per PR/MR, color-coded where the forge can tell reliably:

- **Mergeable** — whether the forge sees a merge conflict or unmet approval rule (e.g. `MERGEABLE`/`CONFLICTING`). This does not reflect CI outcome.
- **Pipeline** — the CI/pipeline outcome for the PR's head commit (e.g. `success`/`failed`/`running`, or `N/A` if the repo has no CI). For GitLab and Gitea this requires a follow-up API call per PR to fetch, since the list endpoints don't expose it directly. GitHub's `BLOCKED` state (e.g. unmet required reviews or status checks) is treated as a failure here too.
- **Review** — the PR's review decision (e.g. `APPROVED`/`REVIEW_REQUIRED`/`CHANGES_REQUESTED`), shown as plain `None` when empty. GitHub exposes this directly (`reviewDecision`); Gitea derives it from the PR's reviews plus the base branch's required-approval count (one extra API call each); GitLab doesn't expose an equivalent today.

A PR is only color-coded ready when Mergeable and Pipeline are both favorable; see the Gitea note below for where this can't be determined with full confidence.

## Features

- **Cross-repo overview** — one table showing every open Renovate (or custom-labeled) PR/MR across all your repos, with age, mergeable state, pipeline status, and (on GitHub) review decision color-coded at a glance (where the forge can tell reliably — see the Gitea note below).
- **Multi-forge, multi-instance** — mix GitHub, GitLab, and Gitea repos in one registry, including multiple self-hosted GitLab or Gitea instances at once, each with its own credentials.
- **Multi-select merge** — tick PRs with `space` and merge them all with `m`; failures don't block the rest, and you get a summary afterward.
- **Multi-select approve** — tick PRs with `space` and approve them all with `a`; failures don't block the rest, and you get a summary afterward.
- **Jump to context** — open a PR in your browser (`o`) or drop into a shell at its local checkout (`s`), with your GitHub token already exported into the shell environment.
- **Configurable** — merge method, detection labels, sort order, and the project registry path are all overridable via a TOML config file.
- **Concurrent fetching** — all repos are queried in parallel via a thread pool, so refreshing dozens of repos takes seconds, not minutes.

## Requirements

- Python 3.11+
- One CLI per forge you actually use:
  - [GitHub CLI (`gh`)](https://cli.github.com/), authenticated or provided a token via config/env (see below)
  - [GitLab CLI (`glab`)](https://gitlab.com/gitlab-org/cli), no pre-login required — lsrenovate injects the token per call (see below)
  - [Gitea CLI (`tea`)](https://gitea.com/gitea/tea), **must be pre-authenticated yourself** via `tea login add` (see the Gitea note below)

## Installation

Requires at least Python 3.11.

With [pipx](https://pipx.pypa.io/):

```bash
pipx install lsrenovate
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install lsrenovate
```

With pip:

```bash
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
     work:
       internal-service:
         forge: gitlab
         url: https://gitlab.example.com/team/internal-service
     personal:
       my-blog:
         forge: gitea
         url: https://gitea.example.com/myuser/my-blog
   ```

   Repos are grouped by an arbitrary top-level key (e.g. `github`, `work`); this key also determines the local checkout path convention `~/Git/<group>/<project>`, used by the "open shell" action. `forge` must be `github`, `gitlab`, or `gitea`.

2. **Provide a GitHub token**, in order of precedence:
   - `GITHUB_TOKEN` environment variable, or
   - `[github].token_command` in the config file — a command that prints the token to stdout, e.g. a password manager CLI, or
   - `[github].token` in the config file (plaintext), or
   - fall back to `gh`'s own stored authentication.

3. **Run it:**

   ```sh
   lsrenovate
   ```

## Configuration

lsrenovate reads an optional TOML config file at your platform's user config directory (e.g. `~/Library/Application Support/lsrenovate/config.toml` on macOS, `~/.config/lsrenovate/config.toml` on Linux):

```toml
merge_method = "squash"                # "squash" (default), "merge", or "rebase"
labels = []                            # default PR label(s) to filter on; all must match
branch_prefixes = ["renovate/"]        # default branch-name prefix(es) to filter on; any one matches
match_mode = "and"                     # "and" (default) or "or" - how labels + branch_prefixes combine
sort_by = "repo"                       # "repo" (default), "age", or "title"
myprojects_path = "~/path/to/myprojects.yaml"  # defaults to a file next to this config

[github]
token = "ghp_..."                      # optional; env var GITHUB_TOKEN takes precedence
token_command = ["kpxc_get_password", "cli://token-gh-cli"]  # optional; takes precedence over token
# labels = ["Renovate"]                # optional; overrides the global `labels` for GitHub only
# branch_prefixes = ["renovate/"]      # optional; overrides the global `branch_prefixes` for GitHub only
# match_mode = "or"                    # optional; overrides the global `match_mode` for GitHub only

# One [gitlab."<host>"] table per self-hosted GitLab instance you use.
# <host> must match the hostname in the repo's url in myprojects.yaml.
[gitlab."gitlab.example.com"]
token = "glpat-..."                    # optional; or use token_command like above
# token_command = ["kpxc_get_password", "cli://token-gitlab-example"]
# api_host = "ssh.gitlab.example.com"   # optional; only needed if `glab auth status`
                                        # shows your token stored under a different
                                        # hostname than the one in your repo URLs
                                        # (e.g. glab auth login ran against an SSH host)
# labels = ["dependencies"]            # optional; overrides the global `labels` for this instance only
# branch_prefixes = ["renovate/"]      # optional; overrides the global `branch_prefixes` for this instance only

# One [gitea."<host>"] table per Gitea instance you use. lsrenovate never
# handles Gitea tokens itself — see the note below.
[gitea."gitea.example.com"]
login = "gitea.example.com"            # optional; defaults to the host itself
# labels = ["dependencies"]            # optional; overrides the global `labels` for this instance only
# branch_prefixes = ["renovate/"]      # optional; overrides the global `branch_prefixes` for this instance only
```

`token_command` (under `[github]` or any `[gitlab."<host>"]` table) is run directly via subprocess (no shell involved, so it works the same regardless of your login shell), and its stdout (trimmed) is used as the token. This avoids storing a plaintext token in the config file. If it fails, lsrenovate falls back to the plaintext `token` (or, for GitHub, `gh`'s own auth) and shows a warning on startup.

### Filtering PRs: labels and branch prefixes

By default, lsrenovate matches PRs by branch prefix `renovate/` (Renovate's own default branch-naming convention), not by label — this works out of the box without any config, since it doesn't depend on which label your Renovate setup happens to use.

Renovate (and similar bots) don't always use the same label across every forge — for example, GitHub/GitLab repos might use `Renovate` while Gitea repos use `dependencies`. Set `labels` at the top level for the default used everywhere, and override it per forge (`[github]`) or per instance (`[gitlab."<host>"]`, `[gitea."<host>"]`) wherever it differs. Multiple labels are always matched with AND semantics — a PR must carry every configured label, not just one.

You can additionally (or instead) filter by branch name prefix via `branch_prefixes`, e.g. `["renovate/"]` to match Renovate's default branch naming. Multiple prefixes are matched with OR semantics — a PR matches if its branch starts with any one of them. `branch_prefixes` follows the same global/per-forge/per-instance override hierarchy as `labels`.

`labels` may be set to `[]` to disable label filtering entirely at a given level (e.g. `labels = []` with `branch_prefixes = ["renovate/"]` set at the same level matches by branch prefix alone). As a convenience, setting `branch_prefixes` at a level without also setting `labels` there implies `labels = []` at that level — you don't need to explicitly disable labels when you only care about the branch prefix. At least one of `labels` or `branch_prefixes` must be non-empty (after overrides are resolved) for each forge/instance actually in use, or lsrenovate raises a configuration error at startup.

When both `labels` and `branch_prefixes` are configured (and non-empty) for the same forge/instance, `match_mode` decides how they combine:

- `"and"` (default): a PR must satisfy both filters.
- `"or"`: a PR is included if it satisfies either filter.

`match_mode = "or"` has an extra cost on GitHub and GitLab: `gh`/`glab` can only pre-filter PRs by label server-side (not by branch prefix), so satisfying OR semantics correctly requires one additional, unfiltered list call per repo (to also catch PRs that match the branch prefix but not the label), whose results are merged with the label-filtered query. This only happens when `match_mode = "or"` **and** both filters are non-empty; the common cases (AND mode, or only one filter configured) stay a single call. Gitea has no server-side label filter at all, so it always does one call and matches everything client-side regardless of `match_mode`.

### Gitea limitation: no token management

The `tea` CLI has no way to pass a token or host per invocation — it only works against named logins that are registered ahead of time. lsrenovate does not manage Gitea credentials at all: before using a Gitea instance, register it yourself with:

```sh
tea login add --name gitea.example.com --url https://gitea.example.com --token <your-token>
```

The `login` field in `[gitea."<host>"]` just tells lsrenovate which registered login name to pass to `tea --login`; it defaults to the host itself, which matches the convention of naming logins after their host.

Gitea's own `mergeable` field is [documented as sometimes wrong upstream](https://github.com/go-gitea/gitea/issues/19755) — it can report `false` for a PR that's actually mergeable. lsrenovate still color-codes it, though: attempting to merge a PR that turns out to have a real conflict fails cleanly with an error rather than silently doing anything harmful, so a wrong "mergeable" signal only costs you one failed merge attempt, not a bad merge. Pipeline/CI status is fetched separately via the Gitea API's combined commit status endpoint (one follow-up call per PR) and factors into the same color, alongside `mergeable`.

## Keybindings

| Key     | Action                                                |
| ------- | ------------------------------------------------------ |
| `space` | Toggle selection of the row under the cursor            |
| `m`     | Merge selected PRs (or the focused one if none selected) |
| `a`     | Approve selected PRs (or the focused one if none selected) |
| `o`     | Open selected PRs (or the focused one) in the browser   |
| `s`     | Check out the focused PR's branch (force-resetting any stale branch) and open a shell there |
| `t`     | Cycle sort order (repo → age → title)                   |
| `r`     | Refresh the PR list                                     |
| `q`     | Quit                                                    |

## Copyright and Licensing

This project is licensed under the Apache License 2.0, copyrighted by Max Mehl. As the project follows the [REUSE](https://reuse.software) best practices, you can find licensing information for each individual file in the [LICENSES](LICENSES) directory or corresponding file headers.
