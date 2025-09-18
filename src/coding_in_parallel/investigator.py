"""Read-only investigative helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from . import ast_index, llm, types

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt {name} not found at {path}")
    return path.read_text().strip()


def recall_candidates(ctx: types.TaskContext) -> List[types.Candidate]:
    """Use the recall prompt to fetch candidate spans."""

    prompt = _load_prompt("ast_recall.txt")
    _ = ast_index.build_index(ctx.repo_path)
    payload = {
        "instance_id": ctx.instance_id,
        "failing_tests": ctx.failing_tests,
    }
    response = llm.complete(prompt.format(**payload))
    try:
        parsed = json.loads(response or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover - guard rails
        raise ValueError(f"Investigator returned non-JSON output: {exc}") from exc
    if isinstance(parsed, list):
        raw_candidates = parsed
    elif isinstance(parsed, dict):
        raw_candidates = parsed.get("candidates", [])
    else:
        raise ValueError("Recall output must be a JSON object with 'candidates'.")
    if not isinstance(raw_candidates, list):
        raise ValueError("'candidates' must be a JSON array.")
    candidates: List[types.Candidate] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            raise ValueError("Each candidate must be a JSON object.")
        raw_spans = raw.get("spans", [])
        if not isinstance(raw_spans, list):
            raise ValueError("Candidate 'spans' must be a list.")
        spans = []
        for span in raw_spans:
            if not isinstance(span, dict):
                raise ValueError("Each span must be a JSON object.")
            spans.append(
                types.AstSpan(
                    file=span["file"],
                    start_line=span["start_line"],
                    end_line=span["end_line"],
                    node_type=span["node_type"],
                    symbol=span.get("symbol"),
                    score=span.get("score"),
                )
            )
        candidates.append(
            types.Candidate(
                id=raw.get("id", f"cand-{len(candidates)+1}"),
                hypothesis=raw.get("hypothesis", ""),
                spans=spans,
                evidence=raw.get("evidence", {}),
            )
        )
    return candidates


def probe(ctx: types.TaskContext, candidates: Iterable[types.Candidate]) -> List[types.Candidate]:
    """Run probe prompt per candidate and attach the response."""

    prompt_template = _load_prompt("probe.txt")
    enriched: List[types.Candidate] = []
    for candidate in candidates:
        payload = {
            "instance_id": ctx.instance_id,
            "candidate_id": candidate.id,
            "hypothesis": candidate.hypothesis,
        }
        response = llm.complete(prompt_template.format(**payload))
        notes = json.loads(response or "{}")
        candidate.evidence.setdefault("probe", notes)
        enriched.append(candidate)
    return enriched


