"""Controller orchestrating the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from . import config as config_module, investigator, planner, proposer, tnr, types, vcs


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
    candidates = investigator.recall_candidates(ctx)
    candidates = investigator.probe(ctx, candidates)
    understanding = planner.synthesize(candidates)
    plan = planner.plan(understanding)[: cfg.search.max_steps]

    transactions: List[tnr.TransactionResult] = []
    for step in plan:
        ctx_files = _load_context(ctx.repo_path, step, cfg.limits.slice_padding_lines)
        step_committed = False
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
                step_committed = True
                break
        if step_committed:
            break

    patch = vcs.final_patch(ctx.repo_path)
    if not patch and transactions:
        last = transactions[-1]
        if last.applied_diff is not None:
            patch = last.applied_diff.unified_diff
    return ControllerResult(final_patch=patch, transactions=transactions, understanding=understanding, plan=plan)


