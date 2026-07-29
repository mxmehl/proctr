"""Functions and data for the `--demo` option of the CLI."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lsrenovate.forges.base import PullRequest
from lsrenovate.projects import Repo


def demo_pull_requests() -> list[PullRequest]:
    """Return canned sample PRs covering every column/color state, for --demo screenshots."""
    now = datetime.now(UTC)

    def repo(forge: str, owner: str, name: str) -> Repo:
        return Repo(
            group=owner,
            name=name,
            forge=forge,
            url=f"https://example.invalid/{owner}/{name}",
            owner=owner,
            local_path=Path(f"~/Git/{owner}/{name}").expanduser(),
        )

    github_repo1 = repo("github", "acme", "webapp")
    github_repo2 = repo("github", "octocat", "example")
    gitlab_repo1 = repo("gitlab", "acme", "infra")
    gitea_repo1 = repo("gitea", "acme", "docs")

    return [
        PullRequest(
            repo=github_repo1,
            number=101,
            title="Update dependency react to v19",
            url="https://example.invalid/acme/webapp/pull/101",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(hours=2),
            mergeable="MERGEABLE",
            pipeline_status="CLEAN",
            merge_ready=True,
            review_decision="APPROVED",
        ),
        PullRequest(
            repo=github_repo1,
            number=98,
            title="Update dependency eslint to v9 (major)",
            url="https://example.invalid/acme/webapp/pull/98",
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=1),
            mergeable="MERGEABLE",
            pipeline_status="UNSTABLE",
            merge_ready=False,
            review_decision="REVIEW_REQUIRED",
        ),
        PullRequest(
            repo=gitlab_repo1,
            number=42,
            title="Update terraform-provider-aws to v5",
            url="https://example.invalid/acme/infra/pull/42",
            created_at=now - timedelta(hours=6),
            updated_at=now - timedelta(hours=1),
            mergeable="CONFLICTING",
            pipeline_status="failed",
            merge_ready=False,
            review_decision="CHANGES_REQUESTED",
        ),
        PullRequest(
            repo=gitea_repo1,
            number=7,
            title="Update docusaurus monorepo",
            url="https://example.invalid/acme/docs/pull/7",
            created_at=now - timedelta(minutes=45),
            updated_at=now - timedelta(minutes=45),
            mergeable="true",
            pipeline_status="success",
            merge_ready=True,
            review_decision="",
        ),
        PullRequest(
            repo=github_repo2,
            number=7,
            title="chore(deps): update dependency lsrenovate to 0.3.0",
            url="https://example.invalid/octocat/example/pull/7",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
            mergeable="MERGEABLE",
            pipeline_status="CLEAN",
            merge_ready=True,
            review_decision="None",
        ),
    ]
