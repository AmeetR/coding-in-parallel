"""Blackboard store for investigative probes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .. import types


@dataclass
class BlackboardStore:
    """Thread-safe store for investigative evidence.

    This is a stub implementation - the full version will include:
    - SCC contraction
    - Monotone demotion
    - Frontier tracking
    - Coverage state
    """

    _suspects: List[types.Node] = field(default_factory=list)
    _probe_patches: List[types.ProbePatch] = field(default_factory=list)
    _evidence: List[Dict[str, Any]] = field(default_factory=list)
    _invariants: List[str] = field(default_factory=list)

    def publish_suspects(self, suspects: List[types.Node]) -> None:
        """Add suspects to the blackboard."""
        self._suspects.extend(suspects)

    def publish_probe_patch(self, patch: types.ProbePatch) -> None:
        """Record a probe patch that was applied."""
        self._probe_patches.append(patch)

    def publish_evidence(self, evidence: Dict[str, Any]) -> None:
        """Record evidence from a probe run."""
        self._evidence.append(evidence)

    def publish_invariant(self, invariant: str) -> None:
        """Record a discovered invariant."""
        self._invariants.append(invariant)

    def snapshot(self) -> types.Blackboard:
        """Return a snapshot of the current blackboard state."""
        return types.Blackboard(
            suspects=list(self._suspects),
            probe_patches=list(self._probe_patches),
            invariants=list(self._invariants),
            evidence=list(self._evidence),
        )

