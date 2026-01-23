"""Combine blackboard evidence into a failure pattern."""

from __future__ import annotations

from . import types


def combine_to_failure_pattern(bb: types.Blackboard) -> types.FailurePattern:
    """Combine blackboard evidence into a unified failure pattern.

    This is a stub implementation that:
    1. Takes the top suspect as primary location
    2. Aggregates invariants from the blackboard
    3. Computes a confidence score

    Args:
        bb: Blackboard with suspects and evidence

    Returns:
        FailurePattern summarizing the likely cause
    """
    if not bb.suspects:
        # Return a minimal failure pattern if no suspects
        return types.FailurePattern(
            summary="No suspects identified",
            primary_location=types.AstSpan(
                file="unknown",
                start_line=0,
                end_line=0,
                node_type="unknown",
            ),
            alternatives=[],
            invariants=list(bb.invariants),
            confidence=0.0,
            assumptions_to_check=[],
            temporary_props=[],
        )

    # Sort suspects by suspicion score
    sorted_suspects = sorted(bb.suspects, key=lambda n: n.suspicion, reverse=True)
    primary = sorted_suspects[0]

    # Build alternatives from remaining suspects
    alternatives = [
        {
            "span": {
                "file": s.span.file,
                "start_line": s.span.start_line,
                "end_line": s.span.end_line,
                "node_type": s.span.node_type,
                "symbol": s.span.symbol,
            },
            "why": f"Suspicion score: {s.suspicion:.2f}",
        }
        for s in sorted_suspects[1:5]  # Top 4 alternatives
    ]

    # Aggregate summary from evidence
    evidence_snippets = []
    for ev in bb.evidence[:3]:
        if "result" in ev:
            evidence_snippets.append(str(ev["result"]))

    summary = f"Primary suspect: {primary.span.symbol or primary.span.file}:{primary.span.start_line}"
    if evidence_snippets:
        summary += f" (evidence: {', '.join(evidence_snippets)})"

    # Confidence based on suspicion and evidence count
    confidence = min(0.95, primary.suspicion * (0.5 + 0.1 * len(bb.evidence)))

    return types.FailurePattern(
        summary=summary,
        primary_location=primary.span,
        alternatives=alternatives,
        invariants=list(bb.invariants),
        confidence=confidence,
        assumptions_to_check=[],
        temporary_props=[],
    )

