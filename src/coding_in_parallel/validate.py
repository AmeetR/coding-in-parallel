"""Validation helpers for proposals and diffs."""

from __future__ import annotations

import re
from typing import Iterable, Set

from . import types

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(?P<afile>[^\s]+) b/(?P<bfile>[^\s]+)", re.MULTILINE)


class ValidationError(RuntimeError):
    """Raised when a proposal fails validation."""


def require_unified_diff(diff: str) -> None:
    """Ensure the string looks like a unified diff."""

    if not diff.startswith("diff --git"):
        raise ValidationError("Diff must start with 'diff --git'.")
    if "@@" not in diff:
        raise ValidationError("Diff must contain a hunk header '@@'.")
    for line in diff.splitlines():
        stripped = line.strip()
        if stripped.startswith("+def") or stripped.startswith("+class"):
            if stripped.endswith("::"):
                raise ValidationError("Suspicious double-colon in definition header.")


def _count_changed_loc(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith("+") or line.startswith("-"))


def _touched_files(diff: str) -> Set[str]:
    matches = _DIFF_HEADER_RE.findall(diff)
    return {b for _a, b in matches}


def ensure_within_limits(
    diff: str,
    *,
    allowed_files: Set[str],
    max_loc: int,
    max_files: int,
    target_spans: Iterable[types.AstSpan],
) -> None:
    """Check diff obeys configured limits."""

    require_unified_diff(diff)
    files = _touched_files(diff)
    if not files:
        raise ValidationError("Diff must touch at least one file header.")
    if len(files) > max_files:
        raise ValidationError("Diff touches too many files.")
    if not files.issubset(allowed_files):
        raise ValidationError("Diff touches files outside of allowed set.")
    loc = _count_changed_loc(diff)
    if loc > max_loc:
        raise ValidationError("Diff changes too many lines.")
    span_files = {span.file for span in target_spans}
    if not files.intersection(span_files):
        raise ValidationError("Diff does not touch any target span files.")


