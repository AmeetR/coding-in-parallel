"""Pydantic models for LLM‑structured outputs in the localization agent."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class ClassificationEvidence(BaseModel):
    """Single evidence item returned by the LLM classifier."""

    kind: str = "llm_inference"
    reason: str = ""
    weight: float = 0.5
    data: Dict[str, Any] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    """Structured classification result for a node."""

    label: Literal["suspect", "cleared", "root_cause"] = "suspect"
    confidence: float = 0.5
    evidence: List[ClassificationEvidence] = Field(default_factory=list)
    reasoning: str = ""
    next_to_investigate: List[str] = Field(default_factory=list)


class ProposalCandidate(BaseModel):
    """Candidate node suggested by the PROPOSE step."""

    qualname: str
    file_path: str = ""
    priority: float = 0.5
    reason: str = ""


class ProbeRequest(BaseModel):
    """Probe request from the PROPOSE step."""

    type: Literal["targeted_test", "print_statement", "assertion"] = "targeted_test"
    target: str
    description: str = ""


class ProposeResult(BaseModel):
    """Structured output from the PROPOSE step."""

    action: Literal["continue", "conclude"] = "continue"
    candidates: List[ProposalCandidate] = Field(default_factory=list)
    probes: List[ProbeRequest] = Field(default_factory=list)
    conclusion_reason: str = ""
