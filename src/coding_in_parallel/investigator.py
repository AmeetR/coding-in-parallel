"""Read-only investigative helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable, List, Sequence

from . import ast_index, llm, types
from .probes import blackboard as bbmod
from .probes import runner as probe_runner
from .probes import sandbox as sbx
from .probes import scheduler as sched

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


# ---- Spec-aligned investigative loop (blackboard + scheduler) ----


def _candidates_to_suspects(candidates: Sequence[types.Candidate], k: int = 7) -> List[types.Node]:
    suspects: List[types.Node] = []
    for cand in candidates:
        for span in cand.spans:
            suspicion = span.score if span.score is not None else 0.5
            suspects.append(
                types.Node(
                    id=f"{cand.id}:{span.file}:{span.start_line}-{span.end_line}",
                    span=span,
                    kind=span.node_type.lower(),
                    hop=0,
                    in_stack=False,
                    suspicion=float(suspicion),
                )
            )
    # Keep top-k by suspicion
    suspects.sort(key=lambda n: n.suspicion, reverse=True)
    return suspects[:k]


def _make_probe_patch(pcb: sched.PCB, node: types.Node) -> types.ProbePatch:
    # Minimal, safe instrumentation: add a marker comment at top of target file
    diff = (
        f"diff --git a/{node.span.file} b/{node.span.file}\n"\
        f"@@\n"\
        f"+# cip_probe {pcb.id} for {node.id}\n"
    )
    return types.ProbePatch(
        id=f"pp-{pcb.id}",
        suspect_id=node.id,
        diff=diff,
        purpose="instrument",
        loc_changed=1,
        rationale="trace entry",
    )


def run_investigations(
    ctx: types.TaskContext,
    candidates: Sequence[types.Candidate],
    *,
    max_probes: int = 7,
    quantum_ops: int = 10,
    timeout_sec: int = 60,
) -> types.Blackboard:
    """Run investigative probes in sandboxes and return a blackboard snapshot.

    This minimal implementation schedules up to max_probes single-action patches
    and computes a naive info_gain from test outcomes.
    """

    store = bbmod.BlackboardStore()
    suspects = _candidates_to_suspects(candidates)
    store.publish_suspects(suspects)
    schedr = sched.Scheduler()
    node_by_id = {n.id: n for n in suspects}
    # Seed PCBs
    for i, n in enumerate(suspects):
        schedr.add_pcb(sched.PCB(id=f"pcb-{i+1}", suspect_id=n.id, quantum_ops=quantum_ops, time_budget=timeout_sec))

    probes_run = 0
    while probes_run < max_probes:
        pcb = schedr.next_pcb()
        if pcb is None:
            break
        node = node_by_id.get(pcb.suspect_id)
        if node is None:
            break
        patch = _make_probe_patch(pcb, node)
        sb = sbx.create(ctx.repo_path)
        try:
            artifacts, gain = probe_runner.investigative_tx(sb, [patch], ctx.test_cmd, timeout_sec=timeout_sec)
            # Update blackboard
            store.publish_probe_patch(patch)
            for art in artifacts:
                store.publish_evidence({"probe_id": art.get("probe_id"), "result": art.get("result")})
            schedr.record_gain(pcb.id, gain)
            probes_run += 1
            # Preemption policy: demote if low gain, boost otherwise
            if gain <= 0.0:
                schedr.preempt(pcb.id)
            else:
                schedr.boost(pcb.id)
        finally:
            sb.cleanup()

    return store.snapshot()

