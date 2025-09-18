"""Planner that turns understanding into plan steps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from . import llm, types

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt {name} not found at {path}")
    return path.read_text().strip()


def synthesize(candidates: Iterable[types.Candidate]) -> types.Understanding:
    """Combine candidate notes into a structured understanding."""

    template = _load_prompt("synthesize.txt")
    payload = {
        "candidates": [candidate.hypothesis for candidate in candidates],
    }
    response = llm.complete(template.format(**payload))
    data = json.loads(response or "{}")
    return types.Understanding(
        summary=data.get("summary", ""),
        invariants=list(data.get("invariants", [])),
        dependencies=list(data.get("dependencies", [])),
    )


def plan(understanding: types.Understanding) -> List[types.PlanStep]:
    """Request a list of plan steps from the LLM."""

    template = _load_prompt("synthesize.txt")
    prompt = f"{template}\nPLAN: {understanding.summary}"
    response = llm.complete(prompt)
    items = json.loads(response or "[]")
    steps: List[types.PlanStep] = []
    for raw in items:
        spans = [
            types.AstSpan(
                file=span["file"],
                start_line=span["start_line"],
                end_line=span["end_line"],
                node_type=span["node_type"],
                symbol=span.get("symbol"),
                score=span.get("score"),
            )
            for span in raw.get("target_spans", [])
        ]
        steps.append(
            types.PlanStep(
                id=raw.get("id", f"step-{len(steps)+1}"),
                intent=raw.get("intent", ""),
                target_spans=spans,
                constraints=list(raw.get("constraints", [])),
                ideal_outcome=raw.get("ideal_outcome", ""),
                check=raw.get("check", "tests"),
            )
        )
    return steps


