"""Controller orchestrating the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from . import combine, config as config_module, investigator, logging, planner, proposer, tnr, types, vcs


@dataclass
class ControllerResult:
    final_patch: str
    transactions: List[tnr.TransactionResult]
    understanding: types.Understanding
    plan: List[types.PlanStep] = field(default_factory=list)


def _load_context(repo_path: str, step: types.PlanStep, padding: int) -> Dict[str, str]:
    root = Path(repo_path)
    grouped: Dict[str, List[str]] = {}
    for span in step.target_spans:
        file_path = root / span.file
        if not file_path.exists():
            continue
        lines = file_path.read_text().splitlines()
        start_index = max(span.start_line - 1 - padding, 0)
        end_index = min(span.end_line + padding, len(lines))
        snippet = lines[start_index:end_index]
        numbered = "\n".join(
            f"{start_index + idx + 1:>4}: {line}" for idx, line in enumerate(snippet)
        )
        grouped.setdefault(span.file, []).append(
            f"LINES {start_index + 1}-{end_index}:\n{numbered}"
        )
    return {file: "\n\n".join(snippets) for file, snippets in grouped.items()}


def _derive_test_cmd(ctx: types.TaskContext, cfg: config_module.Config) -> str:
    """Prefer a targeted -k expression built from failing test names when enabled.

    Falls back to ctx.test_cmd unchanged when no failing tests available.
    """
    if cfg.gates.targeted_tests and ctx.failing_tests:
        names: List[str] = []
        for nodeid in ctx.failing_tests:
            if not nodeid:
                continue
            # Prefer the test function name after '::'
            parts = nodeid.split("::")
            name = parts[-1] if parts else nodeid
            if name:
                names.append(name)
        if names:
            expr = " or ".join(sorted(set(names)))
            return f"pytest -q -k \"{expr}\""
    return ctx.test_cmd


def run_controller(
    ctx: types.TaskContext,
    *,
    config: config_module.Config | None = None,
) -> ControllerResult:
    """Run the investigation → planning → execution loop."""

    cfg = config or config_module.Config.default()

    # Set up logging
    logger = logging.RunLogger(cfg.logging.dir, ctx.instance_id, stream=getattr(cfg.logging, "stream", False))
    logger.log_event(
        "controller.start",
        instance_id=ctx.instance_id,
        repo=ctx.repo_path,
        failing_tests=len(ctx.failing_tests or []),
        test_cmd=ctx.test_cmd,
    )

    # Capture baseline to compute cumulative diff across transactions
    baseline = vcs.checkpoint(ctx.repo_path)
    logger.log_event("vcs.checkpoint", baseline=baseline)

    candidates = investigator.recall_candidates(ctx)
    logger.log_json("candidates", [
        {
            "id": c.id,
            "hypothesis": c.hypothesis,
            "spans": [
                {
                    "file": s.file,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "node_type": s.node_type,
                    "symbol": s.symbol,
                    "score": s.score,
                }
                for s in c.spans
            ],
        }
        for c in candidates
    ])
    logger.log_event("candidates.recalled", count=len(candidates))
    candidates = investigator.probe(ctx, candidates)
    logger.log_event("candidates.probed", count=len(candidates))

    use_landmarks = getattr(cfg.search, "use_landmarks", False)
    investigations_enabled = getattr(cfg.search, "investigations_enabled", False)

    if use_landmarks and investigations_enabled:
        # Run investigative probes with scheduler + blackboard
        logger.log_event("investigations.start")
        bb = investigator.run_investigations(
            ctx,
            candidates,
            max_probes=max(1, cfg.search.diffs_per_step),  # reuse a small budget
            quantum_ops=cfg.limits.slice_padding_lines // 8 or 10,
            timeout_sec=60,
        )
        logger.log_event("investigations.done", suspects=len(bb.suspects), invariants=len(bb.invariants), evidence=len(bb.evidence))
        # Log blackboard snapshot
        logger.log_json("blackboard", {
            "suspects": [
                {
                    "id": n.id,
                    "span": {
                        "file": n.span.file,
                        "start_line": n.span.start_line,
                        "end_line": n.span.end_line,
                        "node_type": n.span.node_type,
                        "symbol": n.span.symbol,
                        "score": n.span.score,
                    },
                    "kind": n.kind,
                    "hop": n.hop,
                    "in_stack": n.in_stack,
                    "suspicion": n.suspicion,
                }
                for n in bb.suspects
            ],
            "invariants": bb.invariants,
            "evidence": bb.evidence,
        })
        logger.log_event("combine.start")
        failure = combine.combine_to_failure_pattern(bb)
        logger.log_event("combine.done", confidence=failure.confidence)
        logger.log_json("failure_pattern", {
            "summary": failure.summary,
            "primary_location": {
                "file": failure.primary_location.file,
                "start_line": failure.primary_location.start_line,
                "end_line": failure.primary_location.end_line,
                "node_type": failure.primary_location.node_type,
                "symbol": failure.primary_location.symbol,
            },
            "invariants": failure.invariants,
            "confidence": failure.confidence,
        })
        logger.log_event("planner.landmarks.start")
        landmarks = planner.plan_landmarks(failure, max_landmarks=3)
        logger.log_event("planner.landmarks.done", count=len(landmarks))
        logger.log_json("landmarks", [
            {
                "id": lm.id,
                "intent": lm.intent,
                "target_spans": [
                    {
                        "file": s.file,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "node_type": s.node_type,
                        "symbol": s.symbol,
                    }
                    for s in lm.target_spans
                ],
                "constraints": lm.constraints,
                "landmark_test": lm.landmark_test,
                "rollback_on": lm.rollback_on,
                "risk": lm.risk,
                "confidence": lm.confidence,
                "try_after": lm.try_after,
            }
            for lm in landmarks
        ])
        plan_steps = planner.landmarks_to_steps(landmarks)
        understanding = types.Understanding(
            summary=failure.summary,
            invariants=failure.invariants,
            dependencies=[],
        )
        plan = plan_steps[: cfg.search.max_steps]
    else:
        logger.log_event("planner.synthesize.start")
        understanding = planner.synthesize(candidates)
        plan = planner.plan(understanding)[: cfg.search.max_steps]
        logger.log_event("planner.synthesize.done", steps=len(plan))

    # Log the understanding and plan
    logger.log_json("understanding", {
        "summary": understanding.summary,
        "invariants": understanding.invariants,
        "dependencies": understanding.dependencies,
    })
    logger.log_json("plan", [
        {
            "id": step.id,
            "intent": step.intent,
            "target_spans": [
                {
                    "file": span.file,
                    "start_line": span.start_line,
                    "end_line": span.end_line,
                    "node_type": span.node_type,
                    "symbol": span.symbol,
                    "score": span.score,
                }
                for span in step.target_spans
            ],
            "constraints": step.constraints,
            "ideal_outcome": step.ideal_outcome,
            "check": step.check,
        }
        for step in plan
    ])

    transactions: List[tnr.TransactionResult] = []
    for step in plan:
        logger.log_event("step.begin", step_id=step.id, intent=step.intent)
        ctx_files = _load_context(ctx.repo_path, step, cfg.limits.slice_padding_lines)
        # Use a potentially more targeted test command during this step
        derived_cmd = _derive_test_cmd(ctx, cfg)
        if derived_cmd and derived_cmd != ctx.test_cmd:
            # Rebind context locally with derived test command
            from dataclasses import replace
            ctx = replace(ctx, test_cmd=derived_cmd)
            logger.log_event("step.test_cmd", step_id=step.id, test_cmd=ctx.test_cmd)

        attempts = max(1, cfg.search.retries_per_step)
        committed = False
        last_logs: List[str] = []
        for _attempt in range(attempts):
            logger.log_event("proposer.start", step_id=step.id)
            proposals = proposer.propose(step, ctx_files, config=cfg)
            finalists = max(1, cfg.search.finalists)
            shortlisted = proposals[:finalists]
            logger.log_event("proposer.done", step_id=step.id, proposals=len(proposals), shortlisted=len(shortlisted))
            if not shortlisted:
                continue
            logger.log_event("txn.start", step_id=step.id, actions=max(1, cfg.tnr.actions_per_txn))
            result = tnr.txn_patch(
                ctx,
                step,
                shortlisted,
                config=cfg,
            )
            transactions.append(result)
            logger.log_event("txn.result", step_id=step.id, committed=result.committed, mu_pre=result.mu_pre, mu_post=result.mu_post)
            last_logs = result.logs
            if result.committed:
                committed = True
                break

        if not committed and last_logs:
            # Reason-aware retry: if recoverable issues, regenerate once
            recoverable = any(
                any(marker in log for marker in ("validation failed", "git apply failed", "static checks failed", "targeted tests failed"))
                for log in last_logs
            )
            if recoverable:
                logger.log_event("proposer.retry", step_id=step.id)
                proposals = proposer.propose(step, ctx_files, config=cfg)
                finalists = max(1, cfg.search.finalists)
                shortlisted = proposals[:finalists]
                if shortlisted:
                    logger.log_event("txn.retry", step_id=step.id)
                    result = tnr.txn_patch(ctx, step, shortlisted, config=cfg)
                    transactions.append(result)
                    logger.log_event("txn.result", step_id=step.id, committed=result.committed, mu_pre=result.mu_pre, mu_post=result.mu_post)
                    if result.committed:
                        committed = True
        # If still not committed, continue to next step (replan hook could be added here)

    # Log the transactions
    logger.log_json("transactions", [
        {
            "step_id": txn.applied_diff.step_id if txn.applied_diff else None,
            "committed": txn.committed,
            "mu_pre": txn.mu_pre,
            "mu_post": txn.mu_post,
            "logs": txn.logs,
        }
        for txn in transactions
    ])

    # Prefer cumulative committed diff from baseline..HEAD; fallback to working tree
    patch = vcs.diff_between(ctx.repo_path, baseline)
    if not patch and transactions:
        last = transactions[-1]
        if last.applied_diff is not None:
            patch = last.applied_diff.unified_diff

    # Log the final patch
    if patch:
        logger.log_text("final_patch", patch)
    logger.log_event("controller.finish", final_patch_len=len(patch or ""))

    return ControllerResult(final_patch=patch, transactions=transactions, understanding=understanding, plan=plan)
