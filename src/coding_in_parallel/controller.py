"""Controller orchestrating the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from . import investigator, planner, proposer, tnr, types, vcs


@dataclass
class ControllerResult:
    final_patch: str
    transactions: List[tnr.TransactionResult]
    understanding: types.Understanding
    plan: List[types.PlanStep] = field(default_factory=list)


def _load_context(repo_path: str, step: types.PlanStep) -> dict[str, str]:
    root = Path(repo_path)
    context: dict[str, str] = {}
    for span in step.target_spans:
        file_path = root / span.file
        if file_path.exists():
            context[span.file] = file_path.read_text()
    return context


def run_controller(ctx: types.TaskContext, *, max_steps: int = 4, diffs_per_step: int = 3) -> ControllerResult:
    """Run the investigation → planning → execution loop."""

    candidates = investigator.recall_candidates(ctx)
    candidates = investigator.probe(ctx, candidates)
    understanding = planner.synthesize(candidates)
    plan = planner.plan(understanding)[:max_steps]

    transactions: List[tnr.TransactionResult] = []
    for step in plan:
        ctx_files = _load_context(ctx.repo_path, step)
        proposals = proposer.propose(step, ctx_files, diffs_per_step)
        result = tnr.txn_patch(ctx, step, proposals, max_actions=diffs_per_step)
        transactions.append(result)
        if result.committed:
            break

    patch = vcs.final_patch(ctx.repo_path)
    if not patch and transactions:
        last = transactions[-1]
        if last.applied_diff is not None:
            patch = last.applied_diff.unified_diff
    return ControllerResult(final_patch=patch, transactions=transactions, understanding=understanding, plan=plan)


