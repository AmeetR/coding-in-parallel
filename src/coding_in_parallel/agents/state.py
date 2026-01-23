"""
AgentState: The TypedDict that flows through the LangGraph localization agent.

This state accumulates evidence in the EvidenceLedger (not in context window),
enabling bounded, focused LLM calls at each step.
"""

from __future__ import annotations

from typing import TypedDict, List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field

from coding_in_parallel.agents.ledger import EvidenceLedger
from coding_in_parallel.agents.context import BaselineContext


# Labels assigned to nodes during investigation
NodeLabel = Literal["unknown", "suspect", "cleared", "root_cause"]


@dataclass(frozen=True)
class QueueItem:
    """A node in the investigation queue with priority metadata."""
    qualname: str
    file_path: str
    priority: float  # higher = investigate first
    reason: str  # why this node was added to queue
    added_by: str  # which step added it (e.g., "BASELINE", "PROPOSE:step_3")


class AgentState(TypedDict, total=False):
    """
    State that flows through the LangGraph localization agent.
    
    Key design principles:
    - Evidence accumulates in `ledger`, not in growing context
    - Each node gets bounded context via `current_context_packet`
    - `investigation_summary` provides stable background for all steps
    
    Workflow:
        BASELINE: Populates baseline_context, investigation_summary, initial queue
        SELECT: Pops from queue, sets current_node
        CLASSIFY: Gets NodeContextPacket, LLM classifies evidence
        RECONCILE: Updates ledger, computes frontier, assigns labels
        PROPOSE: LLM suggests next nodes or probes
        (loop until queue empty or max_steps reached)
    """
    
    # === Inputs (set once at start) ===
    repo_root: str
    test_command: str
    failing_tests: List[str]
    traceback_output: str
    
    # === BASELINE outputs ===
    baseline_context: BaselineContext
    investigation_summary: str  # LLM-generated high-level summary
    qualname_to_span: Dict[str, Dict[str, Any]]  # qualname -> {file, line_start, line_end, symbol}
    
    # === Investigation state ===
    ledger: EvidenceLedger
    queue: List[QueueItem]  # priority queue of nodes to investigate
    current_node: Optional[str]  # qualname of node being classified
    
    # === Per-step context (rewritten each CLASSIFY) ===
    current_context_packet: Optional[Dict[str, Any]]  # serialized NodeContextPacket
    
    # === Control flow ===
    step_count: int
    max_steps: int
    
    # === Outputs ===
    root_causes: List[str]  # qualnames labeled as root_cause
    final_suspects: List[Dict[str, Any]]  # ranked suspects with evidence
    done: bool
    done_reason: str  # "converged", "max_steps", "queue_empty"
    
    # === Probe tracking ===
    pending_probes: List[Dict[str, Any]]
    probe_results: List[Dict[str, Any]]


def create_initial_state(
    repo_root: str,
    test_command: str,
    failing_tests: List[str],
    traceback_output: str,
    max_steps: int = 20,
) -> AgentState:
    """Create initial agent state with empty ledger and queue."""
    return AgentState(
        repo_root=repo_root,
        test_command=test_command,
        failing_tests=failing_tests,
        traceback_output=traceback_output,
        baseline_context=None,  # type: ignore
        investigation_summary="",
        ledger=EvidenceLedger(),
        queue=[],
        current_node=None,
        current_context_packet=None,
        step_count=0,
        max_steps=max_steps,
        root_causes=[],
        final_suspects=[],
        done=False,
        done_reason="",
        pending_probes=[],
        probe_results=[],
        qualname_to_span={},
    )
