<!--
SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>
SPDX-License-Identifier: CC0-1.0
-->

# AGENTS.md

Notes for AI agents working on this codebase. Read the README for user-facing behavior; this file covers non-obvious implementation knowledge and workflow requirements.

## Required workflow

- Never guess a forge CLI's flags/fields/JSON shape. Verify live via `--help` or a real command run before implementing anything against `gh`, `glab`, or `tea`.
- Every forge adapter change needs both a mocked pytest test AND live verification against the user's real repos before being considered done. The user's real config and project registry live at their platform config dir and configured `myprojects_path` — use those for live checks, not synthetic data.
- Run the full check suite after every change: `mise run test-all` (ruff check, ruff format check, ty check, pytest, and reuse lint). Use `mise run fix-all` to auto-fix ruff formatting/lint issues first.
- Secrets are never echoed. The user pastes tokens into the real config file directly; don't ask for or print token values.
- This is a single-user personal project (the user is the only consumer). Hard deprecations are fine — no backward-compat shims needed when changing config schema or field semantics.

## Column semantics (the core design decision of this project)

The table has two independent signals per PR/MR, and conflating them was the source of a real production bug (GitLab MR silently mergeable despite a failed pipeline). Keep them separate:

- **Mergeable** — conflict/approval state only (no CI). `PullRequest.mergeable`.
- **Pipeline** — CI/pipeline outcome only. `PullRequest.pipeline_status`.
- **merge_ready** (`bool | None`) — normalized "safe to merge" signal combining both, used only to color the **Mergeable** cell. `None` means "can't tell, don't color."
- The **Pipeline** cell is colored independently via `_pipeline_cell()` in `app.py`, keyed off the raw status text (`PIPELINE_SUCCESS_VALUES`/`PIPELINE_FAILURE_VALUES`), not off `merge_ready`. This lets CI outcome show green/red even on forges where `merge_ready` itself is `None`.

When a forge's `mergeable`-type field is untrustworthy, the deciding question is: **does trusting it wrongly cause silent harm, or just a failed merge attempt?** All three `merge_pr()` implementations never raise and report failure cleanly on a real conflict — so a wrong positive signal only costs one failed attempt, not a bad merge. This is why Gitea's `mergeable` field is trusted for `merge_ready` despite being documented as sometimes wrong upstream (go-gitea/gitea#19755): the asymmetric-risk argument that justified distrusting GitLab's `detailed_merge_status` (which could let a broken pipeline through silently) does not apply to a field that only gates a safely-failing merge call.

## Forge-specific gotchas

- **GitHub**: `mergeStateStatus` (`CLEAN`/`UNSTABLE`/etc.) already encodes CI outcome — `UNSTABLE` specifically means failing commit status. No follow-up call needed; don't "fix" this to look like GitLab/Gitea. `gh pr checkout <n>` **without `-f` silently leaves a stale local branch untouched** if one already exists with the same name (verified live) — since Renovate reuses branch names across unrelated updates, checkout actions must always pass `-f`.
- **GitLab** (`glab`): `mr list --output json` does **not** include `head_pipeline`/pipeline info at all. Getting pipeline status requires one follow-up `mr view <iid> --output json` call per MR. `has_conflicts` (bool) is the correct conflict-only signal — don't reuse `detailed_merge_status` (it conflates conflicts, approvals, and other blockers). `glab`'s stored auth host can differ from the repo URL's host (e.g. SSH-keyed logins) — see `GitLabInstanceConfig.api_host`. `glab mr checkout <n>` without `-f` correctly refuses with an error on a diverged local branch (safer default than gh's), but still needs `-f` to actually reset it.
- **Gitea** (`tea`): `pulls list` has no server-side label filter (filter client-side on the comma-separated `labels` field) and no pipeline/status field at all. Get CI status via one follow-up `tea api /repos/{owner}/{repo}/commits/{ref}/status` call per PR (the combined commit status endpoint — same concept as GitHub's commit statuses). `tea` has no per-invocation token/host mechanism; users must pre-register instances via `tea login add`. All JSON field values from `tea pulls list --fields ...` are strings, including booleans (`"mergeable": "true"`, not a real JSON bool) — compare with `== "true"`, not `is True`. `tea pulls checkout <n>` has no force flag at all: it always fetches the PR's head ref and checks it out **detached**, deliberately bypassing any stale local branch of the same name rather than trusting it. That's safe but not push-ready, so `GiteaForge.checkout_pr` resolves the head branch name via a `pulls list` lookup and follows up with `git checkout -B <branch> origin/<branch>` to land on a real, force-reset branch.

## Testing conventions

- Mock at the `subprocess.run` level with `side_effect=[...]` when an adapter makes multiple calls (e.g. GitLab/Gitea's list + follow-up status call) — order matters and must match the real call sequence.
- When changing a field's meaning (not just its name), update every consuming test's fixture values, not just the field name — a renamed-but-stale fixture will pass for the wrong reason.

## Spawning subprocesses/shells

proctr normally runs via `uv run`, which mutates the current process's env (`VIRTUAL_ENV`, mise/uv session markers, and a `PATH` with proctr's own `.venv/bin` prepended). Stripping individual known-bad vars is a losing game — there's always another one (confirmed live: fixing `VIRTUAL_ENV` alone still left a stale `PATH` with `.venv/bin` in it). The actual fix in `action_open_shell`/`_shell_env()`: spawn the shell with `-l` (login shell, so it re-sources its own startup files) AND reset `PATH` to `os.defpath` first, so mise/asdf's shell hook rebuilds `PATH` from a clean baseline instead of diffing against an already-polluted one — this reproduces what a brand new terminal window gives you. Things only the OS/terminal session provides (not shell startup files), like `SSH_AUTH_SOCK`, are left inherited as-is since a login shell can't regenerate them and `git push` over SSH depends on it.
