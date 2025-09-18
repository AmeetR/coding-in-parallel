"""Gate execution for transactions."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Tuple


def run_static_checks(repo_path: str) -> Tuple[bool, str]:
    """Run lightweight static checks using ``py_compile``."""

    root = Path(repo_path)
    py_files = [str(path) for path in root.rglob("*.py") if path.is_file()]
    if not py_files:
        return True, "no python files"
    cmd = [sys.executable, "-m", "py_compile", *py_files]
    proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    success = proc.returncode == 0
    output = proc.stdout + proc.stderr
    return success, output


def run_targeted_tests(test_cmd: str, repo_path: str) -> Tuple[bool, str]:
    """Run the provided targeted test command."""

    if not test_cmd:
        return True, "no tests configured"
    proc = subprocess.run(
        shlex.split(test_cmd),
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    success = proc.returncode == 0
    output = proc.stdout + proc.stderr
    return success, output


