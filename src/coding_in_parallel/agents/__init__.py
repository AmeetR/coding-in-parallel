"""
LangGraph-based agents for the coding-in-parallel pipeline.

The localization agent uses a graph-guided "Explore-and-Judge" loop:
  BASELINE → (SELECT → CLASSIFY → RECONCILE → PROPOSE)* → DONE
"""

from coding_in_parallel.agents.state import AgentState
from coding_in_parallel.agents.ledger import EvidenceLedger
from coding_in_parallel.agents.context import BaselineContext, NodeContextPacket

__all__ = [
    "AgentState",
    "EvidenceLedger",
    "BaselineContext",
    "NodeContextPacket",
]

