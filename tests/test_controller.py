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
        unified_diff="""diff --git a/mod.py b/mod.py\n@@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n""",
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


