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
    predictions_path = tmp_path / "preds.jsonl"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n"
        "  provider:\n"
        "  name:\n"
    )

    def fake_run_controller(ctx: types.TaskContext, *, config):
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
        "--config",
        str(config_path),
        "--predictions-out",
        str(predictions_path),
        "--model-name",
        "unit-test-model",
    ])

    assert output_path.read_text().startswith("diff --git")
    preds = predictions_path.read_text().strip().splitlines()
    assert len(preds) == 1
    data = json.loads(preds[0])
    assert data["instance_id"] == "example-1"
    assert data["model_name_or_path"] == "unit-test-model"
    assert data["model_patch"].startswith("diff --git")
