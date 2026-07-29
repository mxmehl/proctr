"""Demo: fetch real Renovate PRs for a couple of repos (read-only)."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

import sys

from proctr.config import load_config
from proctr.forges.github import GitHubForge
from proctr.projects import load_repos


def main() -> None:
    cfg = load_config()
    repos = load_repos(cfg.myprojects_path, forge="github")
    forge = GitHubForge(github_token=cfg.github_token, labels=cfg.labels)

    sample = repos[:3]
    print(f"Fetching Renovate PRs for {len(sample)} repos: {[r.full_name for r in sample]}\n")

    for repo in sample:
        try:
            prs = forge.list_matching_prs(repo)
        except Exception as exc:  # noqa: BLE001 - demo script, show any failure
            print(f"{repo.full_name}: ERROR: {exc}")
            continue
        print(f"{repo.full_name}: {len(prs)} open Renovate PR(s)")
        for pr in prs:
            state = pr.pipeline_status
            print(f"  #{pr.number} {pr.title!r} mergeable={pr.mergeable} state={state}")


if __name__ == "__main__":
    sys.exit(main())
