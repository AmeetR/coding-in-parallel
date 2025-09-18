import json
from pathlib import Path
import subprocess

import pytest

from coding_in_parallel import controller, main, types


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    subprocess.run(["git", "add", "mod.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def test_main_cli_writes_patch_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path):
    instance = {
        "instance_id": "example-1",
        "test_cmd": "pytest -k add",
        "failing_tests": ["tests/test_mod.py::test_add"],
    }
    instance_path = tmp_path / "instance.json"
    instance_path.write_text(json.dumps(instance))
    output_path = tmp_path / "patch.diff"

    def fake_run_controller(ctx: types.TaskContext):
        return controller.ControllerResult(
            final_patch="diff --git a/mod.py b/mod.py\n",
            transactions=[],
            understanding=types.Understanding("", [], []),
            plan=[],
        )

    monkeypatch.setattr(controller, "run_controller", fake_run_controller)

    main.main([
        "--repo",
        str(repo),
        "--task",
        str(instance_path),
        "--out",
        str(output_path),
        "--test-cmd",
        "pytest -k add",
    ])

    assert output_path.read_text().startswith("diff --git")

