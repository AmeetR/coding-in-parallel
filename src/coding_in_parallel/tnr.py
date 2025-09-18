"""Transactional no-regression execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List

from . import config as config_module, gates, types, validate, vcs


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
    config: config_module.Config,
) -> TransactionResult:
    """Attempt to apply one of the provided diff proposals as a transaction."""

    repo_path = ctx.repo_path
    head = vcs.checkpoint(repo_path)
    allowed_files = {span.file for span in step.target_spans}
    logs: List[str] = []

    if config.gates.targeted_tests:
        baseline_ok, baseline_output = gates.run_targeted_tests(ctx.test_cmd, repo_path)
        if not baseline_ok:
            logs.append(f"baseline targeted tests failing: {baseline_output.strip()}")
        mu_pre = 0 if baseline_ok else 1
    else:
        mu_pre = _measure_mu(repo_path)

    for attempt, proposal in enumerate(proposals, start=1):
        if attempt > max(1, config.tnr.actions_per_txn):
            logs.append("Reached transaction action budget; stopping attempts.")
            break
        try:
            validate.ensure_within_limits(
                proposal.unified_diff,
                allowed_files=allowed_files,
                max_loc=config.limits.max_loc_changes,
                max_files=config.limits.max_files_per_diff,
                target_spans=step.target_spans,
                padding_lines=config.limits.slice_padding_lines,
            )
        except validate.ValidationError as exc:
            logs.append(f"validation failed: {exc}")
            continue

        try:
            vcs.apply_diff(proposal.unified_diff, repo_path)
        except RuntimeError as exc:
            logs.append(f"git apply failed: {exc}")
            vcs.revert(repo_path, head)
            continue

        mu_candidate = None
        if not config.gates.targeted_tests:
            mu_candidate = _measure_mu(repo_path)
            if config.tnr.require_mu_nonworsening and mu_candidate > mu_pre:
                logs.append(f"mu worsened from {mu_pre} to {mu_candidate}; rolling back.")
                vcs.revert(repo_path, head)
                continue

        if config.gates.static:
            ok, output = gates.run_static_checks(repo_path)
            if not ok:
                logs.append(f"static checks failed: {output.strip()}")
                vcs.revert(repo_path, head)
                continue

        if config.gates.targeted_tests:
            ok, output = gates.run_targeted_tests(ctx.test_cmd, repo_path)
            mu_post = 0 if ok else 1
            if not ok:
                logs.append(f"targeted tests failed: {output.strip()}")
                vcs.revert(repo_path, head)
                continue
        else:
            mu_post = mu_candidate if mu_candidate is not None else _measure_mu(repo_path)
        if config.tnr.require_mu_nonworsening and mu_post > mu_pre:
            logs.append(f"mu worsened from {mu_pre} to {mu_post}; rolling back.")
            vcs.revert(repo_path, head)
            continue

        vcs.commit(repo_path, f"txn:{step.id}")
        return TransactionResult(True, proposal, mu_pre, mu_post, logs=logs)

    vcs.revert(repo_path, head)
    return TransactionResult(False, None, mu_pre, mu_pre, logs=logs)


