from pathlib import Path
import subprocess

import pytest

from coding_in_parallel import config as config_module, controller, investigator, planner, proposer, tnr, types


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    subprocess.run(["git", "add", "mod.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _init_git_repo(tmp_path)
    return tmp_path


def test_run_controller_applies_committed_diff(monkeypatch: pytest.MonkeyPatch, repo: Path):
    ctx = types.TaskContext(
        repo_path=str(repo),
        failing_tests=["tests/test_mod.py::test_add"],
        test_cmd="pytest -k add",
        targeted_expr=None,
        instance_id="example-1",
        metadata={},
    )
    candidate = types.Candidate(
        id="cand-1",
        hypothesis="add subtracts",
        spans=[types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef")],
        evidence={},
    )
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=candidate.spans,
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    diff = types.DiffProposal(
        step_id="step-1",
        unified_diff="""diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n""",
        rationale="fix",
    )

    monkeypatch.setattr(investigator, "recall_candidates", lambda ctx: [candidate])
    monkeypatch.setattr(investigator, "probe", lambda ctx, cands: cands)
    monkeypatch.setattr(planner, "synthesize", lambda cands: types.Understanding("Fix add", [], []))
    monkeypatch.setattr(planner, "plan", lambda understanding: [step])
    monkeypatch.setattr(proposer, "propose", lambda step, ctx_files, config: [diff])

    def fake_txn(context, plan_step, proposals, *, config):
        return tnr.TransactionResult(
            committed=True,
            applied_diff=diff,
            mu_pre=0,
            mu_post=1,
        )

    monkeypatch.setattr(tnr, "txn_patch", fake_txn)

    cfg = config_module.Config.default()
    result = controller.run_controller(ctx, config=cfg)
    assert result.final_patch == diff.unified_diff
    assert result.transactions[0].committed


def test_run_controller_processes_all_steps(monkeypatch: pytest.MonkeyPatch, repo: Path):
    """Test that controller processes all plan steps, not just the first committed one."""
    ctx = types.TaskContext(
        repo_path=str(repo),
        failing_tests=["tests/test_mod.py::test_add"],
        test_cmd="pytest -k add",
        targeted_expr=None,
        instance_id="example-1",
        metadata={},
    )

    # Create two steps
    step1 = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=[types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef")],
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    step2 = types.PlanStep(
        id="step-2",
        intent="Add docstring",
        target_spans=[types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef")],
        constraints=[],
        ideal_outcome="function documented",
        check="static",
    )

    candidate = types.Candidate(
        id="cand-1",
        hypothesis="add subtracts",
        spans=step1.target_spans,
        evidence={},
    )

    diff1 = types.DiffProposal(
        step_id="step-1",
        unified_diff="""diff --git a/mod.py b/mod.py\n@@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n""",
        rationale="fix",
    )
    diff2 = types.DiffProposal(
        step_id="step-2",
        unified_diff="""diff --git a/mod.py b/mod.py\n@@\n+def add(x, y):\n+    \"\"\"Add two numbers.\"\"\"\n+    return x + y\n""",
        rationale="add docstring",
    )

    monkeypatch.setattr(investigator, "recall_candidates", lambda ctx: [candidate])
    monkeypatch.setattr(investigator, "probe", lambda ctx, cands: cands)
    monkeypatch.setattr(planner, "synthesize", lambda cands: types.Understanding("Fix add", [], []))
    monkeypatch.setattr(planner, "plan", lambda understanding: [step1, step2])
    # Avoid LLM dependency by stubbing proposer
    monkeypatch.setattr(proposer, "propose", lambda step, ctx_files, config: [diff1] if step.id == "step-1" else [diff2])

    call_count = 0
    def fake_txn(context, plan_step, proposals, *, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First step succeeds
            return tnr.TransactionResult(
                committed=True,
                applied_diff=diff1,
                mu_pre=0,
                mu_post=1,
            )
        else:
            # Second step also succeeds
            return tnr.TransactionResult(
                committed=True,
                applied_diff=diff2,
                mu_pre=1,
                mu_post=1,
            )

    monkeypatch.setattr(tnr, "txn_patch", fake_txn)

    cfg = config_module.Config.default()
    result = controller.run_controller(ctx, config=cfg)

    # Should have processed both steps
    assert len(result.transactions) == 2
    assert result.transactions[0].committed
    assert result.transactions[1].committed
    # Final patch should contain both diffs
    assert "def add(x, y):" in result.final_patch
    assert "\"\"\"Add two numbers.\"\"\"" in result.final_patch


def test_run_controller_with_logging(monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path):
    """Test that controller integrates with RunLogger to persist artifacts."""
    from coding_in_parallel import logging

    ctx = types.TaskContext(
        repo_path=str(repo),
        failing_tests=["tests/test_mod.py::test_add"],
        test_cmd="pytest -k add",
        targeted_expr=None,
        instance_id="example-1",
        metadata={},
    )

    candidate = types.Candidate(
        id="cand-1",
        hypothesis="add subtracts",
        spans=[types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef")],
        evidence={},
    )
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=candidate.spans,
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    diff = types.DiffProposal(
        step_id="step-1",
        unified_diff="""diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n""",
        rationale="fix",
    )

    monkeypatch.setattr(investigator, "recall_candidates", lambda ctx: [candidate])
    monkeypatch.setattr(investigator, "probe", lambda ctx, cands: cands)
    monkeypatch.setattr(planner, "synthesize", lambda cands: types.Understanding("Fix add", [], []))
    monkeypatch.setattr(planner, "plan", lambda understanding: [step])
    monkeypatch.setattr(proposer, "propose", lambda step, ctx_files, config: [diff])

    def fake_txn(context, plan_step, proposals, *, config):
        return tnr.TransactionResult(
            committed=True,
            applied_diff=diff,
            mu_pre=0,
            mu_post=1,
        )

    monkeypatch.setattr(tnr, "txn_patch", fake_txn)

    # Mock the logger to capture calls
    logged_calls = []
    original_log_json = logging.RunLogger.log_json
    original_log_text = logging.RunLogger.log_text

    def mock_log_json(self, name: str, data):
        logged_calls.append(('json', name, data))
        return original_log_json(self, name, data)

    def mock_log_text(self, name: str, text: str):
        logged_calls.append(('text', name, text))
        return original_log_text(self, name, text)

    monkeypatch.setattr(logging.RunLogger, 'log_json', mock_log_json)
    monkeypatch.setattr(logging.RunLogger, 'log_text', mock_log_text)

    # Create a logger instance
    logger = logging.RunLogger(str(tmp_path / "test_run"))
    # Build config with logging dir set (frozen dataclass)
    cfg = config_module.Config.from_dict({"logging": {"dir": str(tmp_path / "test_runs")}})

    # Run controller with logging config
    result = controller.run_controller(ctx, config=cfg)

    # Verify logging happened
    assert len(logged_calls) > 0
    # Should have logged understanding, plan, and transactions at minimum
    logged_names = [name for _, name, _ in logged_calls]
    assert any('understanding' in name for name in logged_names)
    assert any('plan' in name for name in logged_names)
    assert any('transactions' in name for name in logged_names)


def test_controller_builds_targeted_test_cmd(monkeypatch: pytest.MonkeyPatch, repo: Path):
    """Controller should derive a -k expression from failing tests when appropriate."""
    from coding_in_parallel import gates

    ctx = types.TaskContext(
        repo_path=str(repo),
        failing_tests=[
            "pkg/tests/test_calc.py::test_add",
            "pkg/tests/test_calc.py::test_sub",
        ],
        test_cmd="pytest -q",  # broad command; should be specialized
        targeted_expr=None,
        instance_id="example-2",
        metadata={},
    )

    candidate = types.Candidate(
        id="cand-1",
        hypothesis="add subtracts",
        spans=[types.AstSpan(file="mod.py", start_line=1, end_line=2, node_type="FunctionDef")],
        evidence={},
    )
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=candidate.spans,
        constraints=[],
        ideal_outcome="add sums",
        check="tests",
    )
    diff = types.DiffProposal(
        step_id="step-1",
        unified_diff="""diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n""",
        rationale="fix",
    )

    monkeypatch.setattr(investigator, "recall_candidates", lambda ctx: [candidate])
    monkeypatch.setattr(investigator, "probe", lambda ctx, cands: cands)
    monkeypatch.setattr(planner, "synthesize", lambda cands: types.Understanding("Fix add", [], []))
    monkeypatch.setattr(planner, "plan", lambda understanding: [step])
    monkeypatch.setattr(proposer, "propose", lambda step, ctx_files, config: [diff])

    seen_cmds = []
    def fake_run_targeted(cmd: str, repo_path: str):
        seen_cmds.append(cmd)
        return True, "ok"

    monkeypatch.setattr(gates, "run_targeted_tests", fake_run_targeted)

    cfg = config_module.Config.default()
    result = controller.run_controller(ctx, config=cfg)
    assert result.transactions[0].committed
    # Must have passed a -k expression containing both test names
    assert seen_cmds and "-k" in seen_cmds[0]
    assert "test_add" in seen_cmds[0] and "test_sub" in seen_cmds[0]
