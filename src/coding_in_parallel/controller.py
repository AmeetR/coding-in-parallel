"""Controller orchestrating the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from . import config as config_module, investigator, logging, planner, proposer, tnr, types, vcs


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


def run_controller(
    ctx: types.TaskContext,
    *,
    config: config_module.Config | None = None,
) -> ControllerResult:
    """Run the investigation → planning → execution loop."""

    cfg = config or config_module.Config.default()

    # Set up logging
    logger = logging.RunLogger(cfg.logging.dir, ctx.instance_id)

    candidates = investigator.recall_candidates(ctx)
    candidates = investigator.probe(ctx, candidates)
    understanding = planner.synthesize(candidates)
    plan = planner.plan(understanding)[: cfg.search.max_steps]

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
        ctx_files = _load_context(ctx.repo_path, step, cfg.limits.slice_padding_lines)
        for _attempt in range(max(1, cfg.search.retries_per_step)):
            proposals = proposer.propose(step, ctx_files, config=cfg)
            finalists = max(1, cfg.search.finalists)
            shortlisted = proposals[:finalists]
            if not shortlisted:
                continue
            result = tnr.txn_patch(
                ctx,
                step,
                shortlisted,
                config=cfg,
            )
            transactions.append(result)
            if result.committed:
                break

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

    patch = vcs.final_patch(ctx.repo_path)
    if not patch and transactions:
        last = transactions[-1]
        if last.applied_diff is not None:
            patch = last.applied_diff.unified_diff

    # Log the final patch
    if patch:
        logger.log_text("final_patch", patch)

    return ControllerResult(final_patch=patch, transactions=transactions, understanding=understanding, plan=plan)


