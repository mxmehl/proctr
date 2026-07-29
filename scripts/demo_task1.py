"""Demo: print all github-forge repos derived from myprojects.yaml."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from __future__ import annotations

from proctr.config import load_config
from proctr.projects import load_repos


def main() -> None:
    cfg = load_config()
    repos = load_repos(cfg.myprojects_path, forge="github")
    print(f"myprojects_path: {cfg.myprojects_path}")
    print(f"merge_method: {cfg.merge_method}")
    print(f"github_token set: {cfg.github_token is not None}")
    print(f"\nFound {len(repos)} github repos:\n")
    for repo in repos:
        exists = "✓" if repo.local_path.is_dir() else "✗"
        print(f"  {exists} {repo.full_name:40s} -> {repo.local_path}")


if __name__ == "__main__":
    main()
