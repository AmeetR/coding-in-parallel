"""Transactional no-regression execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List

from . import gates, types, validate, vcs

_MAX_LOC = 12
_MAX_FILES = 2


@dataclass
class TransactionResult:
    committed: bool
    applied_diff: types.DiffProposal | None
    mu_pre: int
    mu_post: int
    logs: List[str] = field(default_factory=list)


def _measure_mu(repo_path: str) -> int:
    proc = subprocess.run(
        ["git", "diff", "--numstat"],
        cwd=repo_path,
        text=True,
        capture_output=True,
    )
    total = 0
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            total += (int(parts[0]) + int(parts[1])) // 2
    return total


def txn_patch(
    ctx: types.TaskContext,
    step: types.PlanStep,
    proposals: Iterable[types.DiffProposal],
    *,
    max_actions: int = 3,
) -> TransactionResult:
    """Attempt to apply one of the provided diff proposals as a transaction."""

    repo_path = ctx.repo_path
    head = vcs.checkpoint(repo_path)
    mu_pre = _measure_mu(repo_path)
    allowed_files = {span.file for span in step.target_spans}

    for attempt, proposal in enumerate(proposals, start=1):
        if attempt > max_actions:
            break
        try:
            validate.ensure_within_limits(
                proposal.unified_diff,
                allowed_files=allowed_files,
                max_loc=_MAX_LOC,
                max_files=_MAX_FILES,
                target_spans=step.target_spans,
            )
        except validate.ValidationError as exc:  # pragma: no cover - guard rails
            return TransactionResult(False, None, mu_pre, mu_pre, logs=[str(exc)])

        try:
            vcs.apply_diff(proposal.unified_diff, repo_path)
        except RuntimeError as exc:
            vcs.revert(repo_path, head)
            return TransactionResult(False, None, mu_pre, mu_pre, logs=[str(exc)])

        ok, output = gates.run_static_checks(repo_path)
        if not ok:
            vcs.revert(repo_path, head)
            return TransactionResult(False, None, mu_pre, mu_pre, logs=[output])

        ok, output = gates.run_targeted_tests(ctx.test_cmd, repo_path)
        if not ok:
            vcs.revert(repo_path, head)
            return TransactionResult(False, None, mu_pre, mu_pre, logs=[output])

        vcs.stage_all(repo_path)
        vcs.commit(repo_path, f"txn:{step.id}")
        mu_post = _measure_mu(repo_path)
        if mu_post <= mu_pre:
            return TransactionResult(True, proposal, mu_pre, mu_post)
        # if mu worsened, rollback and continue.
        vcs.revert(repo_path, head)

    vcs.revert(repo_path, head)
    return TransactionResult(False, None, mu_pre, mu_pre)


