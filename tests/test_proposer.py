import json
from pathlib import Path

import pytest

from coding_in_parallel import config as config_module, llm, proposer, types


def test_propose_returns_diff_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    response = json.dumps(
        [
            {
                "step_id": "step-1",
                "unified_diff": "diff --git a/mod.py b/mod.py\n@@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n",
                "rationale": "Swap subtraction for addition",
            }
        ]
    )

    def fake_complete(prompt: str, **_: object) -> str:
        assert "Output JSON ONLY" in prompt
        return response

    monkeypatch.setattr(llm, "complete", fake_complete)
    step = types.PlanStep(
        id="step-1",
        intent="Fix add",
        target_spans=[
            types.AstSpan(
                file="mod.py", start_line=1, end_line=2, node_type="FunctionDef", symbol="add"
            )
        ],
        constraints=[],
        ideal_outcome="add returns sum",
        check="tests",
    )
    cfg = config_module.Config.default()
    proposals = proposer.propose(
        step,
        {"mod.py": "LINES 1-2:\n   1: def add(x, y):\n   2:     return x - y"},
        config=cfg,
    )
    assert proposals and proposals[0].rationale.startswith("Swap")

