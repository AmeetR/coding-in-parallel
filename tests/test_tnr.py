import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from coding_in_parallel import config as config_module, gates, tnr, types, validate, vcs


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    subprocess.run(["git", "add", "mod.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    _init_git_repo(tmp_path)
    return tmp_path


def _make_context(repo_path: Path) -> types.TaskContext:
    return types.TaskContext(
        repo_path=str(repo_path),
        failing_tests=["tests/test_mod.py::test_add"],
        test_cmd="pytest -k add",
        targeted_expr=None,
        instance_id="example-1",
        metadata={},
    )


def test_txn_patch_commits_when_checks_pass(monkeypatch: pytest.MonkeyPatch, git_repo: Path):
    ctx = _make_context(git_repo)
    cfg = config_module.Config.default()
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=[
            types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef"),
        ],
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    diff = """diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n"""

    monkeypatch.setattr(gates, "run_static_checks", lambda repo: (True, "ok"))
    monkeypatch.setattr(gates, "run_targeted_tests", lambda cmd, repo: (True, "tests pass"))

    result = tnr.txn_patch(
        ctx,
        step,
        [types.DiffProposal(step_id=step.id, unified_diff=diff, rationale="fix")],
        config=cfg,
    )
    assert result.committed
    assert result.mu_post == 0
    assert "return x + y" in (git_repo / "mod.py").read_text()


def test_txn_patch_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch, git_repo: Path):
    ctx = _make_context(git_repo)
    cfg = config_module.Config.default()
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=[
            types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef"),
        ],
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    bad_diff = """diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y)::\n+    return x + y\n"""

    monkeypatch.setattr(gates, "run_static_checks", lambda repo: (False, "syntax error"))
    monkeypatch.setattr(gates, "run_targeted_tests", lambda cmd, repo: (True, "tests pass"))

    with pytest.raises(validate.ValidationError):
        validate.require_unified_diff(bad_diff)

    # Provide a valid diff but fail gates.
    diff = """diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n"""
    monkeypatch.setattr(gates, "run_static_checks", lambda repo: (False, "syntax error"))

    result = tnr.txn_patch(
        ctx,
        step,
        [types.DiffProposal(step_id=step.id, unified_diff=diff, rationale="fix")],
        config=cfg,
    )
    assert not result.committed
    assert "return x - y" in (git_repo / "mod.py").read_text()


def test_txn_patch_rolls_back_when_mu_worsens(monkeypatch: pytest.MonkeyPatch, git_repo: Path):
    ctx = _make_context(git_repo)
    cfg = config_module.Config.default()
    cfg = replace(cfg, gates=replace(cfg.gates, targeted_tests=False))
    step = types.PlanStep(
        id="step-1",
        intent="Add dead code",
        target_spans=[
            types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef"),
        ],
        constraints=[],
        ideal_outcome="", 
        check="",
    )
    diff = """diff --git a/mod.py b/mod.py\n@@ -1,2 +1,5 @@\n def add(x, y):\n-    return x - y\n+    return x - y\n+\n+def helper():\n+    return 41\n"""

    monkeypatch.setattr(gates, "run_static_checks", lambda repo: (True, "ok"))

    result = tnr.txn_patch(
        ctx,
        step,
        [types.DiffProposal(step_id=step.id, unified_diff=diff, rationale="noop")],
        config=cfg,
    )
    assert not result.committed
    assert any("mu worsened" in log for log in result.logs)
    assert "helper" not in (git_repo / "mod.py").read_text()


