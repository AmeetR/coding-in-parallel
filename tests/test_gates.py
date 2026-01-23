import sys
from pathlib import Path

from coding_in_parallel import gates
from coding_in_parallel.runtime import CommandResult


def test_run_static_checks_detects_syntax_error(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("def broken(:\n    pass\n")
    ok, output = gates.run_static_checks(str(tmp_path))
    assert not ok
    assert "SyntaxError" in output


def test_run_targeted_tests_executes_command(tmp_path: Path):
    script = tmp_path / "script.py"
    script.write_text("import sys; sys.exit(0)")
    ok, output = gates.run_targeted_tests(f"{sys.executable} {script}", str(tmp_path))
    assert ok


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


def test_run_static_checks_uses_runtime(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("def ok():\n    return 1\n")
    rt = _FakeRuntime()
    ok, output = gates.run_static_checks(str(tmp_path), runtime=rt)
    assert ok
    assert rt.commands
    cmd = rt.commands[0]
    assert cmd[0] == "python"
    assert "py_compile" in cmd


def test_run_targeted_tests_uses_runtime(tmp_path: Path):
    rt = _FakeRuntime()
    ok, output = gates.run_targeted_tests("pytest -q", str(tmp_path), runtime=rt)
    assert ok
    assert rt.commands == ["pytest -q"]
