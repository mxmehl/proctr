"""Tests for the shared label/branch-prefix filter-combining logic."""

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Max Mehl <https://mehl.mx>

import pytest

from proctr.forges.base import branch_matches_prefixes, combine_match


@pytest.mark.parametrize(
    ("branch", "prefixes", "expected"),
    [
        ("renovate/foo", ["renovate/"], True),
        ("dependabot/foo", ["renovate/", "dependabot/"], True),
        ("main", ["renovate/"], False),
        ("main", [], False),
    ],
)
def test_branch_matches_prefixes(branch: str, prefixes: list[str], expected: bool) -> None:
    """A branch matches if it starts with any configured prefix (OR semantics)."""
    assert branch_matches_prefixes(branch, prefixes) is expected


@pytest.mark.parametrize(
    ("label_match", "branch_match", "labels_enabled", "branch_enabled", "match_mode", "expected"),
    [
        # Only labels enabled: branch_match is irrelevant.
        (True, False, True, False, "and", True),
        (False, True, True, False, "and", False),
        # Only branch enabled: label_match is irrelevant.
        (False, True, False, True, "and", True),
        (False, False, False, True, "or", False),
        # Both enabled, AND mode: both must match.
        (True, True, True, True, "and", True),
        (True, False, True, True, "and", False),
        (False, True, True, True, "and", False),
        # Both enabled, OR mode: either is enough.
        (True, False, True, True, "or", True),
        (False, True, True, True, "or", True),
        (False, False, True, True, "or", False),
        # Neither enabled: matches by default (validated not to happen at config-load time).
        (False, False, False, False, "and", True),
    ],
)
def test_combine_match(
    *,
    label_match: bool,
    branch_match: bool,
    labels_enabled: bool,
    branch_enabled: bool,
    match_mode: str,
    expected: bool,
) -> None:
    """combine_match's truth table across all four labels/branch enabled combinations."""
    assert (
        combine_match(
            label_match=label_match,
            branch_match=branch_match,
            labels_enabled=labels_enabled,
            branch_enabled=branch_enabled,
            match_mode=match_mode,
        )
        is expected
    )
