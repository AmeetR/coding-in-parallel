"""
EvidenceLedger: The global evidence accumulator for the localization agent.

Maintains:
- L: Local origin evidence (observations made at a specific node)
- P_fwd, P_bwd: Directional propagation evidence (evidence that flows along edges)
- G_S: Causal subgraph (the slice of the full graph relevant to the bug)
- frontier: Current set of root cause candidates
- labels: Node classifications (unknown → suspect → cleared | root_cause)

Key invariant: Labels are monotonically demoted (no flapping between states).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Literal, Any
from collections import defaultdict


NodeLabel = Literal["unknown", "suspect", "cleared", "root_cause"]

# Label ordering for monotone demotion
LABEL_ORDER: Dict[NodeLabel, int] = {
    "unknown": 0,
    "suspect": 1,
    "cleared": 2,
    "root_cause": 3,
}


@dataclass
class LocalEvidence:
    """Evidence observed directly at a node (L in the formalism)."""
    qualname: str
    kind: str  # "stack_hit", "token_hit", "assertion_match", "probe_result", etc.
    source: str  # origin of evidence (e.g., "traceback:line:42")
    reason: str  # human-readable explanation
    weight: float  # contribution to suspicion score
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PropagatedEvidence:
    """Evidence propagated along an edge (P in the formalism)."""
    from_node: str
    to_node: str
    direction: Literal["forward", "backward"]  # forward = callee→caller, backward = caller→callee
    kind: str  # "blame_propagation", "taint_flow", "control_dependency"
    reason: str
    weight: float
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceLedger:
    """
    Global evidence accumulator.
    
    This is the "memory" of the investigation that persists across all steps,
    while individual LLM calls only see bounded context packets.
    """
    
    # Local evidence by node
    local_evidence: Dict[str, List[LocalEvidence]] = field(
        default_factory=lambda: defaultdict(list)
    )
    
    # Propagated evidence (forward: callee→caller, backward: caller→callee)
    propagated_fwd: List[PropagatedEvidence] = field(default_factory=list)
    propagated_bwd: List[PropagatedEvidence] = field(default_factory=list)
    
    # Causal subgraph: edges in the slice relevant to the bug
    # Format: (from_qualname, to_qualname, edge_type)
    causal_graph: Set[Tuple[str, str, str]] = field(default_factory=set)
    
    # Current frontier: nodes that could be root causes
    frontier: Set[str] = field(default_factory=set)
    
    # Node labels (monotonically demoted)
    labels: Dict[str, NodeLabel] = field(default_factory=lambda: defaultdict(lambda: "unknown"))
    
    # Suspicion scores (accumulated from evidence)
    scores: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    
    # Nodes that have been fully classified
    visited: Set[str] = field(default_factory=set)
    
    def add_local_evidence(self, evidence: LocalEvidence) -> None:
        """Add local evidence observed at a node."""
        self.local_evidence[evidence.qualname].append(evidence)
        self.scores[evidence.qualname] += evidence.weight
        
        # Any evidence makes a node at least a suspect
        if self.labels[evidence.qualname] == "unknown":
            self.labels[evidence.qualname] = "suspect"
    
    def add_propagated_evidence(self, evidence: PropagatedEvidence) -> None:
        """Add evidence propagated along an edge."""
        if evidence.direction == "forward":
            self.propagated_fwd.append(evidence)
        else:
            self.propagated_bwd.append(evidence)
        
        # Add edge to causal graph
        self.causal_graph.add((evidence.from_node, evidence.to_node, evidence.kind))
        
        # Update scores
        self.scores[evidence.to_node] += evidence.weight * 0.5  # decay factor
    
    def set_label(self, qualname: str, label: NodeLabel) -> bool:
        """
        Set label with monotone demotion enforcement.
        
        Returns True if label was updated, False if blocked by monotonicity.
        """
        current = self.labels[qualname]
        if LABEL_ORDER[label] >= LABEL_ORDER[current]:
            self.labels[qualname] = label
            return True
        return False
    
    def mark_visited(self, qualname: str) -> None:
        """Mark a node as fully classified."""
        self.visited.add(qualname)
    
    def get_evidence_summary(self, qualname: str) -> Dict[str, Any]:
        """Get summary of all evidence for a node (for remediation handoff)."""
        local = self.local_evidence.get(qualname, [])
        
        # Find propagated evidence involving this node
        prop_to = [e for e in self.propagated_fwd + self.propagated_bwd 
                   if e.to_node == qualname]
        prop_from = [e for e in self.propagated_fwd + self.propagated_bwd 
                     if e.from_node == qualname]
        
        return {
            "qualname": qualname,
            "label": self.labels[qualname],
            "score": self.scores[qualname],
            "local_evidence": [
                {"kind": e.kind, "source": e.source, "reason": e.reason, "weight": e.weight}
                for e in local
            ],
            "propagated_to": [
                {"from": e.from_node, "kind": e.kind, "reason": e.reason}
                for e in prop_to
            ],
            "propagated_from": [
                {"to": e.to_node, "kind": e.kind, "reason": e.reason}
                for e in prop_from
            ],
            "visited": qualname in self.visited,
        }
    
    def compute_frontier(self) -> Set[str]:
        """
        Compute the current frontier (potential root causes).
        
        Frontier = suspects that have no suspect ancestors in G_S.
        Uses SCC contraction for cycles.
        """
        suspects = {q for q, label in self.labels.items() if label == "suspect"}
        
        if not suspects:
            return set()
        
        # Build adjacency from causal graph (only among suspects)
        adj: Dict[str, Set[str]] = defaultdict(set)
        for from_node, to_node, _ in self.causal_graph:
            if from_node in suspects and to_node in suspects:
                adj[from_node].add(to_node)
        
        # Find nodes with no incoming edges from other suspects
        has_incoming = set()
        for targets in adj.values():
            has_incoming.update(targets)
        
        frontier = suspects - has_incoming
        self.frontier = frontier
        return frontier
    
    def get_ranked_suspects(self, top_k: int = 10) -> List[Dict[str, Any]]:
        """Get top suspects ranked by score with full evidence."""
        suspects = [
            (qualname, self.scores[qualname])
            for qualname, label in self.labels.items()
            if label in ("suspect", "root_cause")
        ]
        suspects.sort(key=lambda x: x[1], reverse=True)
        
        return [
            self.get_evidence_summary(qualname)
            for qualname, _ in suspects[:top_k]
        ]

