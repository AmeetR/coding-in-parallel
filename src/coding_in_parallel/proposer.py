"""Diff proposer producing unified diff candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from . import config as config_module, llm, types

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt {name} not found at {path}")
    return path.read_text().strip()


def _format_span_summary(step: types.PlanStep) -> str:
    parts = []
    for span in step.target_spans:
        symbol = f" {span.symbol}" if span.symbol else ""
        parts.append(
            f"- {span.file}:{span.start_line}-{span.end_line} ({span.node_type}{symbol})"
        )
    return "\n".join(parts) if parts else "- (no target spans provided)"


def propose(
    step: types.PlanStep,
    ctx_files: Dict[str, str],
    *,
    config: config_module.Config,
) -> List[types.DiffProposal]:
    """Produce up to *k* unified diff proposals for *step*."""

    prompt = _load_prompt("propose_diff.txt")
    context_lines = []
    for file, content in ctx_files.items():
        context_lines.append(f"FILE: {file}\n{content}")
    payload = {
        "step": step.intent,
        "span_summary": _format_span_summary(step),
        "context": "\n\n".join(context_lines) or "(no context available)",
        "k": config.search.diffs_per_step,
        "max_loc": config.limits.max_loc_changes,
    }
    formatted_prompt = prompt.format(**payload)
    response = llm.complete(formatted_prompt)
    try:
        items = json.loads(response or "[]")
    except json.JSONDecodeError as exc:  # pragma: no cover - guard rails
        raise ValueError(f"Proposer returned non-JSON output: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("Proposer output must be a JSON list of proposals.")
    proposals: List[types.DiffProposal] = []
    for raw in items[: config.search.diffs_per_step]:
        if not isinstance(raw, dict):
            raise ValueError("Each proposal must be a JSON object with diff fields.")
        diff = raw.get("unified_diff")
        if not isinstance(diff, str):
            raise ValueError("Proposal missing 'unified_diff' string field.")
        proposals.append(
            types.DiffProposal(
                step_id=str(raw.get("step_id", step.id)),
                unified_diff=diff,
                rationale=raw.get("rationale"),
            )
        )
    return proposals


