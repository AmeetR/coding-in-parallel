import sys
from pathlib import Path

from coding_in_parallel import gates


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

