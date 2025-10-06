"""Planner that turns understanding into plan steps."""

from __future__ import annotations

import json
from dataclasses import asdict
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
    try:
        data = json.loads(response or "{}")
    except json.JSONDecodeError:
        # Fallback: coerce raw string into a summary
        data = {"summary": (response or "").strip(), "invariants": [], "dependencies": []}
    # Some models may return a list; coerce to dict sensibly
    if isinstance(data, list):
        # If list of strings, join; if list of objects, take fields if present
        if all(isinstance(x, str) for x in data):
            data = {"summary": "; ".join(x.strip() for x in data if x.strip()), "invariants": [], "dependencies": []}
        elif data:
            first = data[0]
            if isinstance(first, dict):
                data = {
                    "summary": first.get("summary", ""),
                    "invariants": first.get("invariants", []),
                    "dependencies": first.get("dependencies", []),
                }
            else:
                data = {"summary": str(first), "invariants": [], "dependencies": []}
        else:
            data = {"summary": "", "invariants": [], "dependencies": []}
    return types.Understanding(
        summary=str(data.get("summary", "")),
        invariants=list(data.get("invariants", [])),
        dependencies=list(data.get("dependencies", [])),
    )


def plan(understanding: types.Understanding) -> List[types.PlanStep]:
    """Request a list of plan steps from the LLM using the dedicated plan prompt."""

    template = _load_prompt("plan.txt")
    payload = {
        "summary": understanding.summary,
        "invariants": understanding.invariants,
        "dependencies": understanding.dependencies,
    }
    prompt = template.format(**payload)
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


def plan_landmarks(failure: types.FailurePattern, *, max_landmarks: int = 3) -> List[types.Landmark]:
    """Single-shot planner to emit up to N Landmarks using a strict JSON prompt."""

    template = _load_prompt("plan_landmarks.txt")
    payload = {
        "failure_pattern": json.dumps(
            {
                "summary": failure.summary,
                "primary_location": asdict(failure.primary_location),
                "alternatives": [
                    {"span": asdict(alt["span"]), "why": alt.get("why", "")} for alt in failure.alternatives
                ],
                "invariants": failure.invariants,
                "confidence": failure.confidence,
                "assumptions_to_check": failure.assumptions_to_check,
                "temporary_props": failure.temporary_props,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "max_landmarks": max_landmarks,
    }
    response = llm.complete(template.format(**payload))
    try:
        items = json.loads(response or "[]")
    except json.JSONDecodeError:
        # Defensive extraction of array body
        start = response.find("[") if response else -1
        end = response.rfind("]") if response else -1
        if start != -1 and end != -1 and end > start:
            items = json.loads(response[start : end + 1])
        else:
            items = []
    lms: List[types.Landmark] = []
    for raw in items[:max_landmarks]:
        spans = [
            types.AstSpan(
                file=span["file"],
                start_line=int(span["start_line"]),
                end_line=int(span["end_line"]),
                node_type=span["node_type"],
                symbol=span.get("symbol"),
            )
            for span in raw.get("target_spans", [])
        ]
        lms.append(
            types.Landmark(
                id=raw.get("id", f"lm-{len(lms)+1}"),
                intent=raw.get("intent", ""),
                target_spans=spans,
                constraints=list(raw.get("constraints", [])),
                landmark_test=raw.get("landmark_test", "pytest -q -k 'not none'"),
                rollback_on=list(raw.get("rollback_on", [])),
                risk=raw.get("risk", "unknown"),
                confidence=float(raw.get("confidence", 0.0)),
                try_after=raw.get("try_after"),
            )
        )
    return lms


def landmarks_to_steps(landmarks: Iterable[types.Landmark]) -> List[types.PlanStep]:
    """Translate Landmarks to PlanSteps for TNR executor compatibility."""

    steps: List[types.PlanStep] = []
    for lm in landmarks:
        steps.append(
            types.PlanStep(
                id=lm.id,
                intent=lm.intent,
                target_spans=list(lm.target_spans),
                constraints=list(lm.constraints),
                ideal_outcome=f"landmark:{lm.landmark_test}",
                check="tests",
            )
        )
    return steps
