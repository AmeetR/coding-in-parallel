"""Probe execution runner."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .. import types
from .sandbox import Sandbox


def investigative_tx(
    sandbox: Sandbox,
    patches: List[types.ProbePatch],
    test_cmd: str,
    *,
    timeout_sec: int = 60,
    baseline_output: str | None = None,
) -> Tuple[List[Dict[str, Any]], float]:
    """Run investigative patches in a sandbox and compute info gain.

    This is a stub implementation that:
    1. Applies patches to the sandbox
    2. Runs the test command
    3. Computes a naive info_gain based on pass/fail

    Args:
        sandbox: Isolated sandbox environment
        patches: Probe patches to apply
        test_cmd: Test command to run
        timeout_sec: Timeout for test execution
        baseline_output: Optional baseline output to compare against for info gain

    Returns:
        Tuple of (artifacts list, info_gain float)
    """
    artifacts: List[Dict[str, Any]] = []

    for patch in patches:
        # Apply the patch in the sandbox
        success = sandbox.apply_patch(patch.diff)

        if not success:
            artifacts.append({
                "probe_id": patch.id,
                "result": "apply_failed",
                "suspect_id": patch.suspect_id,
            })
            continue

        # Run tests
        passed, output = sandbox.run_command(test_cmd, timeout_sec=timeout_sec)

        # Compute naive info gain:
        # - If test passes now, high info gain (we may have found the fix)
        # - If test still fails but output changed, medium info gain
        # - If output is identical, low info gain
        if passed:
            info_gain = 1.0
            result = "test_passed"
        else:
            # Compare output to baseline if available
            if baseline_output and output and output.strip() != baseline_output.strip():
                info_gain = 0.5
                result = "test_failed_changed"
            else:
                info_gain = 0.1
                result = "test_failed"

        artifacts.append({
            "probe_id": patch.id,
            "result": result,
            "suspect_id": patch.suspect_id,
            "output_snippet": output[:500] if output else "",
            "info_gain": info_gain,
        })

        # Revert the patch for next iteration
        sandbox.revert()

    # Aggregate info gain (max across patches)
    total_gain = max((a.get("info_gain", 0.1) for a in artifacts), default=0.0)

    return artifacts, total_gain
