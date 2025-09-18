"""Core datatypes for coding-in-parallel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AstSpan:
    """Represents a span of code located by the AST index."""

    file: str
    start_line: int
    end_line: int
    node_type: str
    symbol: Optional[str] = None
    score: Optional[float] = None


@dataclass
class Candidate:
    """Investigation candidate returned from the recall phase."""

    id: str
    hypothesis: str
    spans: List[AstSpan]
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Understanding:
    """High-level understanding synthesised from probes."""

    summary: str
    invariants: List[str]
    dependencies: List[str]


@dataclass
class PlanStep:
    """Atomic step in the execution plan."""

    id: str
    intent: str
    target_spans: List[AstSpan]
    constraints: List[str]
    ideal_outcome: str
    check: str


@dataclass
class DiffProposal:
    """Unified diff proposal returned from the proposer."""

    step_id: str
    unified_diff: str
    rationale: Optional[str] = None


@dataclass
class TaskContext:
    """Execution context for a SWE-bench task."""

    repo_path: str
    failing_tests: List[str]
    test_cmd: str
    targeted_expr: Optional[str]
    instance_id: str
    metadata: Dict[str, Any]


