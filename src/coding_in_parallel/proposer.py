"""Diff proposer producing unified diff candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from . import llm, types

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt {name} not found at {path}")
    return path.read_text().strip()


def propose(step: types.PlanStep, ctx_files: Dict[str, str], k: int) -> List[types.DiffProposal]:
    """Produce up to *k* unified diff proposals for *step*."""

    prompt = _load_prompt("propose_diff.txt")
    context_lines = []
    for file, content in ctx_files.items():
        context_lines.append(f"FILE: {file}\n{content}")
    payload = {
        "step": step.intent,
        "spans": [span.file for span in step.target_spans],
        "context": "\n".join(context_lines),
        "k": k,
    }
    response = llm.complete(prompt.format(**payload))
    items = json.loads(response or "[]")
    proposals: List[types.DiffProposal] = []
    for raw in items[:k]:
        proposals.append(
            types.DiffProposal(
                step_id=raw.get("step_id", step.id),
                unified_diff=raw["unified_diff"],
                rationale=raw.get("rationale"),
            )
        )
    return proposals


