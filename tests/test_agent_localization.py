"""Integration-style tests for the LangGraph localization agent baseline."""

from pathlib import Path

import pytest

from coding_in_parallel.agents.localization import baseline_node
from coding_in_parallel.agents.state import create_initial_state
from coding_in_parallel import llm


PYTEST_OUTPUT = """
============================= test session starts ==============================
tests/test_calculator.py::test_calculate_sum_basic FAILED
=================================== FAILURES ===================================
tests/test_calculator.py:4: AssertionError
E   AssertionError: Expected 5 but got 3
"""


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    src = tmp_path / "calculator.py"
    src.write_text(
        '"""Calculator module with a bug."""\n\n'
        "def calculate_sum(a: int, b: int) -> int:\n"
        "    return a - b\n"
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_calculator.py").write_text(
        "from calculator import calculate_sum\n\n"
        "def test_calculate_sum_basic():\n"
        "    assert calculate_sum(2, 3) == 5\n"
    )
    return tmp_path


def test_baseline_node_populates_context(sample_repo: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_complete(prompt: str, **_: object) -> str:
        return "summary"

    monkeypatch.setattr(llm, "complete", fake_complete)
    state = create_initial_state(
        repo_root=str(sample_repo),
        test_command="pytest -q",
        failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
        traceback_output=PYTEST_OUTPUT,
        max_steps=5,
    )

    result = baseline_node(state)
    baseline = result["baseline_context"]
    assert baseline.initial_suspects, "Expected initial suspects"
    assert baseline.call_graph_slice.nodes, "Expected call graph nodes"
    assert result["qualname_to_span"], "Expected qualname_to_span mapping"
