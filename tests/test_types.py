import dataclasses

import pytest

from coding_in_parallel import types


def test_ast_span_dataclass_fields():
    span = types.AstSpan(
        file="example.py",
        start_line=1,
        end_line=5,
        node_type="FunctionDef",
        symbol="example",
        score=0.9,
    )
    assert dataclasses.is_dataclass(types.AstSpan)
    assert span.file == "example.py"
    assert span.start_line == 1
    assert span.end_line == 5
    assert span.node_type == "FunctionDef"
    assert span.symbol == "example"
    assert span.score == pytest.approx(0.9)


def test_plan_step_check_enum():
    step = types.PlanStep(
        id="step-1",
        intent="Fix the bug",
        target_spans=[
            types.AstSpan(
                file="example.py",
                start_line=10,
                end_line=12,
                node_type="FunctionDef",
            )
        ],
        constraints=["keep API"],
        ideal_outcome="Tests pass",
        check="tests",
    )
    assert step.check in {"compile", "lint", "tests", "custom"}


