"""Read-only investigative helpers."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Optional

from . import ast_index, llm, types
from .probes import blackboard as bbmod
from .probes import runner as probe_runner
from .probes import sandbox as sbx
from .probes import scheduler as sched

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


# =============================================================================
# Graph-Guided Localization (new approach)
# =============================================================================

def recall_candidates_grounded(
    ctx: types.TaskContext,
    traceback_output: Optional[str] = None,
    max_steps: int = 10,
) -> List[types.Candidate]:
    """
    Use graph-guided localization instead of LLM-only recall.
    
    This approach:
    1. Parses the traceback to extract stack frames
    2. Matches assertion strings in source code
    3. Uses AST index for callgraph expansion
    4. Runs a LangGraph agent to classify suspects
    
    Falls back to LLM-only recall if localization fails.
    """
    from .agents.localization import run_localization
    
    # If no traceback provided, try to get it by running tests
    if not traceback_output:
        traceback_output = _capture_test_output(ctx.repo_path, ctx.test_cmd, runtime=ctx.runtime)
    
    if not traceback_output:
        # Fall back to LLM-only
        return recall_candidates(ctx)
    
    try:
        result = run_localization(
            repo_root=ctx.repo_path,
            test_command=ctx.test_cmd,
            failing_tests=ctx.failing_tests or [],
            traceback_output=traceback_output,
            max_steps=max_steps,
        )
        
        # Convert localization result to Candidates
        candidates: List[types.Candidate] = []
        qualname_to_span = result.get("qualname_to_span", {}) or {}
        for i, suspect in enumerate(result.get("final_suspects", [])):
            qualname = suspect.get("qualname", "")
            score = suspect.get("score", 0.5)
            label = suspect.get("label", "suspect")
            evidence = suspect.get("local_evidence", [])
            
            # Build reason summary
            reasons = [e.get("reason", "") for e in evidence if e.get("reason")]
            reason_summary = "; ".join(reasons[:3]) if reasons else f"Graph-guided analysis ({label})"
            
            # Resolve file/line info from localization map
            spans = []
            meta = qualname_to_span.get(qualname)
            if isinstance(meta, dict):
                spans.append(types.AstSpan(
                    file=meta.get("file", ""),
                    start_line=int(meta.get("line_start", 0) or 0),
                    end_line=int(meta.get("line_end", 0) or 0),
                    node_type="FunctionDef",
                    symbol=meta.get("symbol"),
                    score=float(score),
                ))
            
            candidates.append(types.Candidate(
                id=f"loc-{i+1}",
                hypothesis=reason_summary,
                spans=spans,
                evidence={
                    "qualname": qualname,
                    "score": score,
                    "label": label,
                    "localization_evidence": evidence,
                    "source": "graph_guided",
                },
            ))
        
        if candidates:
            return candidates
            
    except Exception as e:
        # Log error and fall back
        import sys
        print(f"[investigator] Graph-guided localization failed: {e}", file=sys.stderr)
    
    # Fall back to LLM-only
    return recall_candidates(ctx)


def _capture_test_output(
    repo_path: str,
    test_cmd: str,
    *,
    timeout: int = 60,
    runtime: Any | None = None,
) -> str:
    """Run tests and capture output including tracebacks."""
    try:
        if runtime is not None:
            result = runtime.exec(test_cmd, timeout_sec=timeout)
            return (result.stdout or "") + "\n" + (result.stderr or "")
        result = subprocess.run(
            test_cmd,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # Combine stdout and stderr
        return result.stdout + "\n" + result.stderr
    except (subprocess.TimeoutExpired, Exception):
        return ""


def _lightweight_pytest_cmd(cmd: str) -> str:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if not parts:
        return cmd
    is_pytest = parts[0] == "pytest"
    is_python_pytest = len(parts) >= 3 and parts[0] == "python" and parts[1] == "-m" and parts[2] == "pytest"
    if not (is_pytest or is_python_pytest):
        return cmd
    insert_at = 1 if is_pytest else 3
    has_quiet = "-q" in parts or "--quiet" in parts
    has_maxfail = any(p == "-x" or p.startswith("--maxfail") for p in parts)
    if not has_quiet:
        parts.insert(insert_at, "-q")
        insert_at += 1
    if not has_maxfail:
        parts.insert(insert_at, "--maxfail=1")
    return shlex.join(parts)


def _probe_test_command(ctx: types.TaskContext) -> str:
    """Prefer minimal failing tests for probes; fall back to a light pytest cmd."""
    nodeids = [nodeid for nodeid in (ctx.failing_tests or []) if nodeid]
    if nodeids:
        return shlex.join(["pytest", "-q", "--maxfail=1", *nodeids])
    if ctx.targeted_expr:
        return shlex.join(["pytest", "-q", "--maxfail=1", "-k", ctx.targeted_expr])
    if ctx.test_cmd:
        return _lightweight_pytest_cmd(ctx.test_cmd)
    return ""


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


def _make_probe_patch(repo_root: Path, pcb: sched.PCB, node: types.Node) -> types.ProbePatch:
    # Minimal, safe instrumentation: add a marker comment near the suspect span.
    file_path = repo_root / node.span.file
    try:
        lines = file_path.read_text().splitlines()
    except Exception:
        lines = []
    insert_line = max(1, node.span.start_line)
    context_line = None
    if lines and 1 <= insert_line <= len(lines):
        context_line = lines[insert_line - 1]
    hunk_lines: List[str] = []
    if context_line is not None:
        # Insert after the context line.
        hunk_header = f"@@ -{insert_line},1 +{insert_line},2 @@"
        hunk_lines = [
            hunk_header,
            f" {context_line}",
            f"+# cip_probe {pcb.id} for {node.id}",
        ]
    else:
        # Append at end of file.
        old_start = len(lines)
        new_start = len(lines) + 1
        hunk_header = f"@@ -{old_start},0 +{new_start},1 @@"
        hunk_lines = [
            hunk_header,
            f"+# cip_probe {pcb.id} for {node.id}",
        ]
    diff = "\n".join(
        [
            f"diff --git a/{node.span.file} b/{node.span.file}",
            f"--- a/{node.span.file}",
            f"+++ b/{node.span.file}",
            *hunk_lines,
            "",
        ]
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
    and computes a naive info_gain from test outcomes. Probes prefer a minimal
    failing-test command when available.
    """

    store = bbmod.BlackboardStore()
    suspects = _candidates_to_suspects(candidates)
    store.publish_suspects(suspects)
    schedr = sched.Scheduler()
    node_by_id = {n.id: n for n in suspects}
    # Seed PCBs
    for i, n in enumerate(suspects):
        schedr.add_pcb(sched.PCB(id=f"pcb-{i+1}", suspect_id=n.id, quantum_ops=quantum_ops, time_budget=timeout_sec))

    # Capture baseline output once to estimate info gain.
    baseline_output = ""
    baseline_ok = False
    probe_cmd = _probe_test_command(ctx)
    if probe_cmd:
        sb = sbx.create(ctx.repo_path)
        sb.runtime = _clone_runtime(ctx.runtime, str(sb.path))
        try:
            baseline_ok, baseline_output = sb.run_command(probe_cmd, timeout_sec=timeout_sec)
        finally:
            sb.cleanup()

    probes_run = 0
    while probes_run < max_probes:
        pcb = schedr.next_pcb()
        if pcb is None:
            break
        node = node_by_id.get(pcb.suspect_id)
        if node is None:
            break
        patch = _make_probe_patch(Path(ctx.repo_path), pcb, node)
        if not probe_cmd:
            break
        sb = sbx.create(ctx.repo_path)
        sb.runtime = _clone_runtime(ctx.runtime, str(sb.path))
        try:
            artifacts, gain = probe_runner.investigative_tx(
                sb,
                [patch],
                probe_cmd,
                timeout_sec=timeout_sec,
                baseline_output=baseline_output,
            )
            # Update blackboard
            store.publish_probe_patch(patch)
            for art in artifacts:
                store.publish_evidence({
                    "probe_id": art.get("probe_id"),
                    "result": art.get("result"),
                    "info_gain": art.get("info_gain"),
                    "suspect_id": art.get("suspect_id"),
                    "output_snippet": art.get("output_snippet"),
                })
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


def _clone_runtime(runtime: Any | None, repo_path: str) -> Any | None:
    if runtime is None:
        return None
    clone = getattr(runtime, "clone_for_repo", None)
    if callable(clone):
        return clone(repo_path)
    return None
