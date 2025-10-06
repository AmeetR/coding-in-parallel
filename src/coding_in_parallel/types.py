"""Core datatypes for coding-in-parallel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from typing import Literal


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


# --- Spec-aligned models (fusion, planning, investigations) ---


@dataclass(frozen=True)
class Node:
    """Localized program entity in the subgraph."""

    id: str
    span: AstSpan
    kind: str
    hop: int
    in_stack: bool
    suspicion: float


@dataclass(frozen=True)
class Subgraph:
    """Neighborhood subgraph around failure signals."""

    nodes: List[Node]
    edges: List[Tuple[str, str, str]]
    slices: Dict[str, str]


@dataclass(frozen=True)
class ProbePatch:
    """A tiny investigative patch applied inside a sandbox only."""

    id: str
    suspect_id: str
    diff: str
    purpose: Literal["instrument", "assert", "reduce"]
    loc_changed: int
    rationale: str


@dataclass(frozen=True)
class ProbeReport:
    """Outcome of a single investigative probe run."""

    id: str
    suspect_id: str
    result: Literal["informative", "uninformative"]
    info_gain: float
    recommendation: Literal["likely_cause", "possible", "unlikely", "unknown"]
    observations: Dict[str, Any]
    artifacts: List[str]


@dataclass
class Blackboard:
    """Shared evidence store for investigations (thread/process safe upstream)."""

    suspects: List[Node] = field(default_factory=list)
    observables: List[Dict[str, Any]] = field(default_factory=list)
    probe_patches: List[ProbePatch] = field(default_factory=list)
    invariants: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FailurePattern:
    """Fused view of the failure with a primary location and alternatives."""

    summary: str
    primary_location: AstSpan
    alternatives: List[Dict[str, Any]]  # each { span: AstSpan, why: str }
    invariants: List[str]
    confidence: float
    assumptions_to_check: List[str]
    temporary_props: List[str]


@dataclass(frozen=True)
class Landmark:
    """Atomic repair landmark with explicit test and risk annotations."""

    id: str
    intent: str
    target_spans: List[AstSpan]
    constraints: List[str]
    landmark_test: str
    rollback_on: List[str]
    risk: str
    confidence: float
    try_after: Optional[str] = None


@dataclass
class TaskContext:
    """Execution context for a SWE-bench task."""

    repo_path: str
    failing_tests: List[str]
    test_cmd: str
    targeted_expr: Optional[str]
    instance_id: str
    metadata: Dict[str, Any]

