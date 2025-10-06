"""VCS plumbing helpers built on Git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional


def _normalize_diff(diff: str) -> str:
    lines = diff.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git"):
            output.append(line)
            parts = line.split()
            a_path = parts[2]
            b_path = parts[3]
            i += 1
            if i < len(lines) and lines[i].startswith("--- "):
                output.append(lines[i])
                i += 1
            else:
                output.append(f"--- {a_path}")
            if i < len(lines) and lines[i].startswith("+++ "):
                output.append(lines[i])
                i += 1
            else:
                output.append(f"+++ {b_path}")
            continue
        output.append(line)
        i += 1
    text = "\n".join(output)
    if diff.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def _run_git(
    repo_path: str,
    *args: str,
    check: bool = True,
    input: Optional[str] = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        input=input,
        text=True,
        capture_output=True,
        **kwargs,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


def apply_diff(diff: str, repo_path: str) -> None:
    """Apply a unified diff to the repository."""

    normalized = _normalize_diff(diff)
    try:
        _run_git(repo_path, "apply", "-", input=normalized)
    except RuntimeError:
        _manual_apply(normalized, repo_path)


def _manual_apply(diff: str, repo_path: str) -> None:
    lines = diff.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("diff --git"):
            i += 1
            continue
        parts = lines[i].split()
        b_path = parts[3][2:]
        i += 1
        # Skip ---/+++ headers if present
        while i < len(lines) and lines[i].startswith("---"):
            i += 1
        while i < len(lines) and lines[i].startswith("+++"):
            i += 1
        hunk: list[str] = []
        while i < len(lines) and not lines[i].startswith("diff --git"):
            hunk.append(lines[i])
            i += 1
        _apply_hunks(repo_path, b_path, hunk)


def _apply_hunks(repo_path: str, file_rel: str, hunk_lines: list[str]) -> None:
    path = Path(repo_path) / file_rel
    original = path.read_text().splitlines(keepends=True)
    pointer = 0
    output: list[str] = []
    for line in hunk_lines:
        if line.startswith("@@"):
            continue
        if line.startswith(" "):
            if pointer < len(original):
                output.append(original[pointer])
                pointer += 1
        elif line.startswith("-"):
            pointer += 1
        elif line.startswith("+"):
            text = line[1:]
            if not text.endswith("\n"):
                text += "\n"
            output.append(text)
    output.extend(original[pointer:])
    path.write_text("".join(output))


def checkpoint(repo_path: str) -> str:
    """Return the current HEAD commit hash."""

    proc = _run_git(repo_path, "rev-parse", "HEAD")
    return proc.stdout.strip()


def revert(repo_path: str, commit_id: str) -> None:
    """Hard reset to the given commit."""

    _run_git(repo_path, "reset", "--hard", commit_id)
    _run_git(repo_path, "clean", "-fd")


def stage_all(repo_path: str) -> None:
    _run_git(repo_path, "add", "-A")


def commit(repo_path: str, message: str) -> str:
    """Create a commit with all staged changes."""

    stage_all(repo_path)
    proc = _run_git(repo_path, "commit", "-m", message)
    return proc.stdout.strip()


def final_patch(repo_path: str) -> str:
    """Return the diff between HEAD and the working tree."""

    proc = _run_git(repo_path, "diff", "HEAD")
    return proc.stdout

def diff_between(repo_path: str, base: str, head: str = "HEAD") -> str:
    """Return the unified diff from base..head (committed changes).

    This captures the cumulative effect across multiple commits, which is
    necessary when each transaction creates its own commit.
    """
    proc = _run_git(repo_path, "diff", f"{base}..{head}")
    return proc.stdout


def clean(repo_path: str) -> None:
    """Discard uncommitted changes."""

    _run_git(repo_path, "reset", "--hard")
    _run_git(repo_path, "clean", "-fd")

