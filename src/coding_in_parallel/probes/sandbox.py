"""Sandbox for isolated probe execution."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from ..runtime import Runtime


@dataclass
class Sandbox:
    """Isolated environment for running investigative probes.

    Default implementation uses a temporary copy of the repository.
    """

    repo_path: str
    _temp_dir: Optional[Path] = field(default=None, init=False)
    _work_path: Optional[Path] = field(default=None, init=False)
    runtime: Runtime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize the sandbox working directory."""
        self._temp_dir = Path(tempfile.mkdtemp(prefix="cip_sandbox_"))
        self._work_path = self._temp_dir / "repo"
        shutil.copytree(self.repo_path, self._work_path, symlinks=True)

    @property
    def path(self) -> Path:
        """Return the sandbox working directory path."""
        if self._work_path is None:
            raise RuntimeError("Sandbox not initialized")
        return self._work_path

    def apply_patch(self, diff: str) -> bool:
        """Apply a unified diff patch to the sandbox.

        Returns True if successful, False otherwise.
        """
        if not diff.strip():
            return True
        try:
            result = subprocess.run(
                ["git", "apply", "--allow-empty", "-"],
                input=diff,
                cwd=self.path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def run_command(
        self,
        command: str,
        *,
        timeout_sec: int = 60,
    ) -> Tuple[bool, str]:
        """Run a shell command in the sandbox.

        Returns (success, output) tuple.
        """
        try:
            if self.runtime is not None:
                result = self.runtime.exec(command, timeout_sec=timeout_sec)
                output = (result.stdout or "") + (result.stderr or "")
                return result.ok, output
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.path,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def revert(self) -> None:
        """Revert all changes in the sandbox."""
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=self.path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=self.path,
                capture_output=True,
            )
        except Exception:
            pass

    def cleanup(self) -> None:
        """Remove the sandbox temporary directory."""
        if self.runtime is not None:
            try:
                self.runtime.close()
            except Exception:
                pass
            self.runtime = None
        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
            self._work_path = None


@dataclass
class WorktreeSandbox(Sandbox):
    """Sandbox backed by a git worktree (fast, low I/O).

    Requires a clean git working tree. Falls back to copy mode if not available.
    """

    _repo_root: Optional[Path] = field(default=None, init=False)
    _worktree_path: Optional[Path] = field(default=None, init=False)
    _head: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._repo_root = Path(self.repo_path)
        self._temp_dir = Path(tempfile.mkdtemp(prefix="cip_worktree_"))
        self._worktree_path = self._temp_dir / "repo"
        self._head = _git_head(self._repo_root)
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(self._worktree_path), self._head or "HEAD"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
        )
        self._work_path = self._worktree_path

    def cleanup(self) -> None:
        if self.runtime is not None:
            try:
                self.runtime.close()
            except Exception:
                pass
            self.runtime = None
        if self._repo_root and self._worktree_path:
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(self._worktree_path)],
                    cwd=self._repo_root,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=self._repo_root,
                    capture_output=True,
                )
            except Exception:
                pass
        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
            self._work_path = None
            self._worktree_path = None


def _git_head(repo_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return None
    return None


def _is_git_repo(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def _is_clean_repo(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == ""
    except Exception:
        return False


def create(
    repo_path: str,
    *,
    mode: str | None = None,
    runtime: Runtime | None = None,
) -> Sandbox:
    """Create a new sandbox for the given repository.

    mode:
      - \"worktree\": use git worktree isolation (requires clean git repo)
      - \"copy\": use temp directory copy (default fallback)
      - None: auto-detect (worktree if possible, else copy)
    """
    root = Path(repo_path)
    if mode == "worktree":
        if _is_git_repo(root) and _is_clean_repo(root):
            sb = WorktreeSandbox(repo_path=repo_path)
            sb.runtime = runtime
            return sb
        # Fall back to copy if worktree is not possible
        sb = Sandbox(repo_path=repo_path)
        sb.runtime = runtime
        return sb
    if mode == "copy":
        sb = Sandbox(repo_path=repo_path)
        sb.runtime = runtime
        return sb
    # Auto mode
    if _is_git_repo(root) and _is_clean_repo(root):
        sb = WorktreeSandbox(repo_path=repo_path)
        sb.runtime = runtime
        return sb
    sb = Sandbox(repo_path=repo_path)
    sb.runtime = runtime
    return sb
