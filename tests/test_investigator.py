import json
import shlex
from pathlib import Path

import pytest

from coding_in_parallel import investigator, llm, types


@pytest.fixture()
def repo_with_bug(tmp_path: Path) -> Path:
    file_path = tmp_path / "mod.py"
    file_path.write_text(
        """def add(x, y):\n    return x-y\n"""
    )
    return tmp_path


def _make_ctx(repo_path: Path) -> types.TaskContext:
    return types.TaskContext(
        repo_path=str(repo_path),
        failing_tests=["tests/test_mod.py::test_add"],
        test_cmd="pytest -k add",
        targeted_expr=None,
        instance_id="example-1",
        metadata={},
    )


def test_recall_candidates_parses_llm_output(monkeypatch: pytest.MonkeyPatch, repo_with_bug: Path):
    ctx = _make_ctx(repo_with_bug)
    response = json.dumps(
        {
            "candidates": [
                {
                    "id": "cand-1",
                    "hypothesis": "The function subtracts instead of adds.",
                    "spans": [
                        {
                            "file": "mod.py",
                            "start_line": 1,
                            "end_line": 2,
                            "node_type": "FunctionDef",
                            "symbol": "add",
                            "score": 0.8,
                        }
                    ],
                    "evidence": {"score": 0.8},
                }
            ]
        }
    )

    def fake_complete(prompt: str, **_: object) -> str:
        assert "Return JSON ONLY" in prompt
        return response

    monkeypatch.setattr(llm, "complete", fake_complete)
    candidates = investigator.recall_candidates(ctx)
    assert candidates and candidates[0].spans[0].file.endswith("mod.py")


def test_probe_appends_notes(monkeypatch: pytest.MonkeyPatch, repo_with_bug: Path):
    ctx = _make_ctx(repo_with_bug)
    candidate = types.Candidate(
        id="cand-1",
        hypothesis="Bug in add",
        spans=[
            types.AstSpan(
                file="mod.py", start_line=1, end_line=2, node_type="FunctionDef", symbol="add"
            )
        ],
        evidence={},
    )
    probe_response = json.dumps(
        {
            "notes": "Function subtracts instead of adding.",
            "assumptions": ["inputs are numbers"],
        }
    )

    def fake_complete(prompt: str, **_: object) -> str:
        assert "probe" in prompt.lower()
        return probe_response

    monkeypatch.setattr(llm, "complete", fake_complete)
    enriched = investigator.probe(ctx, [candidate])
    assert "probe" in enriched[0].evidence
    assert "Function subtracts" in enriched[0].evidence["probe"]["notes"]


def test_probe_test_command_prefers_failing_tests(repo_with_bug: Path):
    ctx = _make_ctx(repo_with_bug)
    cmd = investigator._probe_test_command(ctx)
    parts = shlex.split(cmd)
    assert parts[0] == "pytest"
    assert "-q" in parts
    assert "--maxfail=1" in parts
    assert "tests/test_mod.py::test_add" in parts


def test_probe_test_command_uses_targeted_expr(repo_with_bug: Path):
    ctx = types.TaskContext(
        repo_path=str(repo_with_bug),
        failing_tests=[],
        test_cmd="pytest -q",
        targeted_expr="add or sub",
        instance_id="example-1",
        metadata={},
    )
    cmd = investigator._probe_test_command(ctx)
    parts = shlex.split(cmd)
    assert parts[0] == "pytest"
    assert "-k" in parts
    assert "--maxfail=1" in parts


def test_lightweight_pytest_cmd_adds_maxfail():
    cmd = investigator._lightweight_pytest_cmd("pytest -k add")
    parts = shlex.split(cmd)
    assert "pytest" in parts[0]
    assert "--maxfail=1" in parts
