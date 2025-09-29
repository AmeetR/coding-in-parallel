import json

import pytest

from coding_in_parallel import planner, llm, types


def test_synthesize_returns_understanding(monkeypatch: pytest.MonkeyPatch):
    response = json.dumps(
        {
            "summary": "The add function subtracts.",
            "invariants": ["inputs remain ints"],
            "dependencies": ["mod.add"],
        }
    )

    def fake_complete(prompt: str, **_: object) -> str:
        assert "synthesize" in prompt.lower()
        return response

    monkeypatch.setattr(llm, "complete", fake_complete)
    understanding = planner.synthesize([])
    assert understanding.summary.startswith("The add function")


def test_plan_produces_plan_steps(monkeypatch: pytest.MonkeyPatch):
    response = json.dumps(
        [
            {
                "id": "step-1",
                "intent": "Correct the arithmetic.",
                "target_spans": [
                    {
                        "file": "mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "node_type": "FunctionDef",
                    }
                ],
                "constraints": ["keep function signature"],
                "ideal_outcome": "add returns x + y",
                "check": "tests",
            }
        ]
    )

    def fake_complete(prompt: str, **_: object) -> str:
        assert "plan" in prompt.lower()
        return response

    understanding = types.Understanding(
        summary="Fix add",
        invariants=[],
        dependencies=[],
    )
    monkeypatch.setattr(llm, "complete", fake_complete)
    steps = planner.plan(understanding)
    assert steps[0].intent.startswith("Correct")
    assert steps[0].target_spans[0].file == "mod.py"


def test_plan_uses_dedicated_prompt_not_synthesize(monkeypatch: pytest.MonkeyPatch):
    """Test that plan() uses the dedicated plan.txt prompt, not synthesize.txt."""
    response = json.dumps([{"id": "step-1", "intent": "test", "target_spans": [], "constraints": [], "ideal_outcome": "test", "check": "tests"}])

    def fake_complete(prompt: str, **_: object) -> str:
        # Should use plan.txt, not synthesize.txt
        assert "Given this understanding of the problem:" in prompt
        assert "Generate a structured plan as JSON array" in prompt
        assert "SUMMARY:" in prompt
        assert "INVARIANTS:" in prompt
        assert "DEPENDENCIES:" in prompt
        return response

    understanding = types.Understanding(
        summary="Test understanding",
        invariants=["test invariant"],
        dependencies=["test dep"],
    )
    monkeypatch.setattr(llm, "complete", fake_complete)
    steps = planner.plan(understanding)
    assert len(steps) == 1
    assert steps[0].id == "step-1"

