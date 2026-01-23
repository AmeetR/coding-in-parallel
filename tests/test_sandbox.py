from pathlib import Path
import subprocess

from coding_in_parallel.probes import sandbox
from coding_in_parallel.runtime import CommandResult


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    subprocess.run(["git", "add", "mod.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_sandbox_worktree_auto(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    sb = sandbox.create(str(repo))
    try:
        assert sb.path.exists()
        # worktree or copy both acceptable; ensure apply_patch works
        ok = sb.apply_patch(
            "diff --git a/mod.py b/mod.py\n"
            "--- a/mod.py\n"
            "+++ b/mod.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(x, y):\n"
            "-    return x - y\n"
            "+def add(x, y):\n"
            "+    return x + y\n"
        )
        assert ok
    finally:
        sb.cleanup()


class _FakeRuntime:
    def __init__(self) -> None:
        self.commands = []

    def exec(self, cmd, *, timeout_sec=None, env=None):
        self.commands.append(cmd)
        return CommandResult(0, "ok", "")

    def close(self) -> None:
        return None

    @property
    def workdir(self) -> str:
        return "/repo"


def test_sandbox_run_command_uses_runtime(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    sb = sandbox.create(str(repo))
    rt = _FakeRuntime()
    sb.runtime = rt
    try:
        ok, output = sb.run_command("pytest -q")
        assert ok
        assert rt.commands == ["pytest -q"]
    finally:
        sb.cleanup()
