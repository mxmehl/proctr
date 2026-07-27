"""Demo: fetch Renovate PRs across all github repos in parallel, with timing."""

from __future__ import annotations

import time

from lsrenovate.config import load_config
from lsrenovate.fetch import fetch_all_prs
from lsrenovate.forges.github import GitHubForge
from lsrenovate.projects import load_repos


def main() -> None:
    cfg = load_config()
    repos = load_repos(cfg.myprojects_path, forge="github")
    forge = GitHubForge(github_token=cfg.github_token, labels=cfg.labels)

    print(f"Fetching Renovate PRs across {len(repos)} repos concurrently...\n")
    start = time.monotonic()
    result = fetch_all_prs(repos, forge)
    elapsed = time.monotonic() - start

    print(
        f"Done in {elapsed:.2f}s: {len(result.pull_requests)} PR(s), {len(result.errors)} repo error(s)\n"
    )
    for pr in result.pull_requests:
        print(f"  {pr.repo.full_name} #{pr.number} {pr.title!r} mergeable={pr.mergeable}")
    for err in result.errors:
        print(f"  ERROR {err.repo.full_name}: {err.error}")


if __name__ == "__main__":
    main()
