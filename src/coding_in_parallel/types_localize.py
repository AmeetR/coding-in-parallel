"""Typed structures for localization (suspect discovery) results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from typing import Literal

from . import types


# Core spans and slices


@dataclass(frozen=True)
class Slice:
    """Prompt slice around a span."""

    file: str
    start_line: int
    end_line: int
    kind: Literal["span", "neighbor"]


@dataclass(frozen=True)
class HammockBlock:
    """Single-entry/single-exit block used for tighter edit allowlists."""

    file: str
    start_line: int
    end_line: int
    kind: Literal["hammock", "approx"]
    entry_id: Optional[str] = None
    exit_id: Optional[str] = None


# Suspects and evidence


@dataclass(frozen=True)
class EvidenceItem:
    """Single piece of evidence with its provenance and reason."""

    kind: Literal["stack_hit", "token_hit", "callgraph", "heuristic", "sbfl", "coverage"]
    source: str  # e.g. "traceback:line:42", "test_foo.py::test_bar", "grep:assertion"
    reason: str  # human-readable: "Function appears in stack frame at line 42"
    weight: float = 1.0  # contribution to score
    data: Dict[str, Any] = field(default_factory=dict)  # raw payload (line, match, etc.)


@dataclass(frozen=True)
class SuspectEvidence:
    """Signals contributing to a suspect's score, with reasons."""

    items: List[EvidenceItem] = field(default_factory=list)  # all evidence with reasons
    # Convenience accessors (derived from items)
    stack_hits: List[Dict[str, Any]] = field(default_factory=list)
    token_hits: List[Dict[str, Any]] = field(default_factory=list)
    callgraph_hops_from_stack: Optional[int] = None
    heuristics: List[str] = field(default_factory=list)
    sbfl: Dict[str, Any] = field(default_factory=dict)

    def summary_reasons(self) -> List[str]:
        """Return list of human-readable reasons for remediation context."""
        return [item.reason for item in self.items if item.reason]


@dataclass(frozen=True)
class Suspect:
    """Resolvable program entity selected for investigation."""

    id: str
    file: str
    span: types.AstSpan
    kind: Literal["function", "method", "class", "module"]
    qualname: Optional[str]
    symbol: Optional[str]
    reason: str = ""  # top-level summary reason for selection (for remediation)
    anchors: Dict[str, Any] = field(default_factory=dict)
    evidence: SuspectEvidence = field(default_factory=SuspectEvidence)
    score: float = 0.0


@dataclass(frozen=True)
class SupportedSubgraph:
    """Bounded callgraph (and optional CFG/blocks) over suspects."""

    nodes: List[Dict[str, Any]]
    edges: List[Tuple[str, str, str]]  # (src_id, dst_id, kind)
    hammocks: Dict[str, List[HammockBlock]] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerSeed:
    """Initial blackboard/ledger seed produced by localization."""

    suspects: List[Suspect]
    labels: Dict[str, List[str]] = field(default_factory=dict)
    frontier: List[str] = field(default_factory=list)
    allowlists: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)
    posterior: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalizationResult:
    """Output contract for the localization step."""

    suspects: List[Suspect]
    subgraph: SupportedSubgraph
    slices: Dict[str, List[Slice]]  # file -> slices
    hammocks: Dict[str, List[HammockBlock]]
    ledger_seed: LedgerSeed

    def reasons_for_remediation(self) -> Dict[str, List[str]]:
        """Return suspect_id -> list of reasons, for passing to remediation."""
        return {
            s.id: [s.reason] + s.evidence.summary_reasons()
            for s in self.suspects
        }
