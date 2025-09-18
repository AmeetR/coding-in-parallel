import subprocess
from pathlib import Path

from coding_in_parallel import vcs


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "file.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_apply_and_final_patch(tmp_path: Path):
    _init_repo(tmp_path)
    diff = """diff --git a/file.txt b/file.txt\n@@\n-hello\n+hello world\n"""
    vcs.apply_diff(diff, str(tmp_path))
    patch = vcs.final_patch(str(tmp_path))
    assert "hello world" in patch
    vcs.revert(str(tmp_path), vcs.checkpoint(str(tmp_path)))

