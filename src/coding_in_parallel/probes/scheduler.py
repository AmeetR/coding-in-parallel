"""Scheduler for probe execution with UCB-like prioritization."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PCB:
    """Probe Control Block - metadata for a scheduled probe."""

    id: str
    suspect_id: str
    quantum_ops: int = 10
    time_budget: int = 60
    priority: float = 1.0
    runs: int = 0
    total_gain: float = 0.0

    @property
    def avg_gain(self) -> float:
        """Average info gain per run."""
        return self.total_gain / max(1, self.runs)


@dataclass
class Scheduler:
    """UCB-style scheduler for probe execution.

    Balances exploration (untried probes) vs exploitation (high-gain probes).

    This is a stub implementation - the full version will include:
    - Bounded concurrency
    - Better UCB tuning
    - Deterministic mode with seed
    """

    _pcbs: Dict[str, PCB] = field(default_factory=dict)
    _total_runs: int = 0
    _exploration_weight: float = 1.4  # UCB exploration constant

    def add_pcb(self, pcb: PCB) -> None:
        """Add a probe control block to the scheduler."""
        self._pcbs[pcb.id] = pcb

    def remove_pcb(self, pcb_id: str) -> None:
        """Remove a PCB from the scheduler."""
        self._pcbs.pop(pcb_id, None)

    def next_pcb(self) -> Optional[PCB]:
        """Select the next PCB to run using UCB.

        Returns None if no PCBs are available.
        """
        if not self._pcbs:
            return None

        # UCB score: avg_gain + exploration_bonus
        def ucb_score(pcb: PCB) -> float:
            if pcb.runs == 0:
                return float("inf")  # Always try untried probes first
            exploration_bonus = self._exploration_weight * math.sqrt(
                math.log(self._total_runs + 1) / pcb.runs
            )
            return pcb.avg_gain + exploration_bonus

        best_pcb = max(self._pcbs.values(), key=ucb_score)
        return best_pcb

    def record_gain(self, pcb_id: str, gain: float) -> None:
        """Record the info gain from a probe run."""
        if pcb_id in self._pcbs:
            pcb = self._pcbs[pcb_id]
            pcb.runs += 1
            pcb.total_gain += gain
            self._total_runs += 1

    def preempt(self, pcb_id: str) -> None:
        """Demote a PCB's priority (low gain)."""
        if pcb_id in self._pcbs:
            self._pcbs[pcb_id].priority *= 0.5

    def boost(self, pcb_id: str) -> None:
        """Boost a PCB's priority (high gain)."""
        if pcb_id in self._pcbs:
            self._pcbs[pcb_id].priority = min(2.0, self._pcbs[pcb_id].priority * 1.5)

    def active_count(self) -> int:
        """Return the number of active PCBs."""
        return len(self._pcbs)

    def get_stats(self) -> Dict[str, float]:
        """Return scheduler statistics."""
        if not self._pcbs:
            return {"total_runs": 0, "avg_gain": 0.0}

        total_gain = sum(p.total_gain for p in self._pcbs.values())
        return {
            "total_runs": self._total_runs,
            "avg_gain": total_gain / max(1, self._total_runs),
            "active_pcbs": len(self._pcbs),
        }

