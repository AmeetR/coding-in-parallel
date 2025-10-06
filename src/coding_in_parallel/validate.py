"""Validation helpers for proposals and diffs."""

from __future__ import annotations

import re
from typing import Iterable, Set

from . import types

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(?P<afile>[^\s]+) b/(?P<bfile>[^\s]+)", re.MULTILINE)
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


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


def _span_map(target_spans: Iterable[types.AstSpan], padding: int) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = {}
    for span in target_spans:
        start = max(1, span.start_line - padding)
        end = max(start, span.end_line + padding)
        spans.setdefault(span.file, []).append((start, end))
    return spans


def _line_allowed(span_ranges: dict[str, list[tuple[int, int]]], file: str, line: int) -> bool:
    ranges = span_ranges.get(file, [])
    for start, end in ranges:
        if start <= line <= end:
            return True
    return False


def ensure_within_limits(
    diff: str,
    *,
    allowed_files: Set[str],
    max_loc: int,
    max_files: int,
    target_spans: Iterable[types.AstSpan],
    padding_lines: int = 0,
    allow_api_change: bool = False,
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

    span_ranges = _span_map(target_spans, padding_lines)
    current_file: str | None = None
    old_line = new_line = None
    # Track signature lines within a hunk to detect true signature edits
    removed_defs: set[str] = set()
    added_defs: set[str] = set()
    for line in diff.splitlines():
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            current_file = header_match.group("bfile")
            old_line = new_line = None
            removed_defs.clear()
            added_defs.clear()
            continue
        if line.startswith("@@"):
            if current_file is None:
                raise ValidationError("Hunk appears before diff header.")
            hunk = _HUNK_HEADER_RE.match(line)
            if not hunk:
                raise ValidationError("Malformed hunk header in diff.")
            old_line = int(hunk.group("old_start"))
            new_line = int(hunk.group("new_start"))
            # reset hunk-level signature tracking
            removed_defs.clear()
            added_defs.clear()
            continue
        if not line or current_file is None:
            continue
        if line.startswith(" "):
            if old_line is not None:
                old_line += 1
            if new_line is not None:
                new_line += 1
            continue
        if line.startswith("-"):
            if old_line is None:
                raise ValidationError("Deletion encountered before hunk header.")
            if not _line_allowed(span_ranges, current_file, old_line):
                raise ValidationError(
                    f"Deletion at {current_file}:{old_line} outside allowed spans."
                )
            # Track signature changes
            if line.startswith("-def ") and not allow_api_change:
                removed_defs.add(line[1:].strip())
            old_line += 1
            continue
        if line.startswith("+"):
            if new_line is None:
                raise ValidationError("Addition encountered before hunk header.")
            if not _line_allowed(span_ranges, current_file, new_line):
                raise ValidationError(
                    f"Addition at {current_file}:{new_line} outside allowed spans."
                )
            # Track signature changes
            if line.startswith("+def ") and not allow_api_change:
                added_defs.add(line[1:].strip())
            new_line += 1
            # After updating per-line, if both sets present and unequal, treat as signature change
            if added_defs and removed_defs and (added_defs != removed_defs) and not allow_api_change:
                raise ValidationError("Public API signature change detected in diff.")
            continue
        # Ignore lines such as "\\ No newline at end of file"
