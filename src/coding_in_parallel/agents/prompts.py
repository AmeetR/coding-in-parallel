"""
Prompt templates for the localization agent.

Each prompt is designed to receive bounded context and produce structured output.
"""

BASELINE_PROMPT = """You are an expert software debugger analyzing a test failure.

## Error Information
{ERROR}

## Stack Trace
{STACK_TRACE}

## Failing Tests
{FAILING_TESTS}

## Code Structure
{CODE_STRUCTURE}

## Call Graph (K-hop from failure)
{CALL_GRAPH}

## Initial Suspects (from static analysis)
{INITIAL_SUSPECTS}

---

Based on this information, provide a high-level investigation summary:

1. **Root Cause Hypothesis**: What do you think is the most likely cause of this failure?
2. **Key Code Paths**: Which functions/methods should be investigated first?
3. **Data Flow**: What data might be corrupted or incorrect?
4. **Investigation Priority**: Rank the initial suspects by likelihood.

Keep your response concise and actionable. Focus on what we know, not speculation.
"""


CLASSIFY_PROMPT = """You are classifying a code location as part of a bug investigation.

## Investigation Summary
{INVESTIGATION_SUMMARY}

---

## Node Under Investigation

### Identity
{NODE}

### Code
```python
{CODE}
```

### Reason for Investigation
{REASON}

### Callers (functions that call this one)
{CALLERS}

### Callees (functions this one calls)
{CALLEES}

### Test Coverage
{TEST_COVERAGE}

### Evidence Already Collected
{EXISTING_EVIDENCE}

---

Analyze this code location and determine if it is:
- **root_cause**: This is where the bug originates
- **suspect**: This contributes to the bug but may not be the root cause
- **cleared**: This code is not involved in the bug

Respond with valid JSON:
```json
{{
  "label": "suspect" | "cleared" | "root_cause",
  "confidence": 0.0-1.0,
  "evidence": [
    {{
      "kind": "code_smell" | "data_flow" | "control_flow" | "test_coverage" | "semantic",
      "reason": "explanation of what you found",
      "weight": 0.0-1.0
    }}
  ],
  "reasoning": "brief explanation of your classification",
  "next_to_investigate": ["qualname1", "qualname2"]
}}
```
"""


PROPOSE_PROMPT = """You are deciding next steps in a bug investigation.

## Investigation Summary
{INVESTIGATION_SUMMARY}

## Current Evidence
{EVIDENCE_SUMMARY}

## Frontier (current root cause candidates)
{FRONTIER}

## Nodes Already Visited
{VISITED}

## Current Queue
{QUEUE}

---

Based on the investigation so far, what should we do next?

Options:
1. **Add candidates**: Suggest new code locations to investigate
2. **Request probes**: Request targeted tests or instrumentation
3. **Conclude**: Declare investigation complete

Respond with valid JSON:
```json
{{
  "action": "continue" | "conclude",
  "candidates": [
    {{
      "qualname": "module.function",
      "file_path": "path/to/file.py",
      "priority": 0.0-1.0,
      "reason": "why investigate this"
    }}
  ],
  "probes": [
    {{
      "type": "targeted_test" | "print_statement" | "assertion",
      "target": "qualname or expression",
      "description": "what this probe will reveal"
    }}
  ],
  "conclusion_reason": "only if action is conclude"
}}
```
"""


def format_baseline_prompt(sections: dict) -> str:
    """Format BASELINE prompt with context sections."""
    return BASELINE_PROMPT.format(
        ERROR=sections.get("ERROR", "Unknown error"),
        STACK_TRACE=sections.get("STACK_TRACE", "No stack trace available"),
        FAILING_TESTS=sections.get("FAILING_TESTS", "No tests specified"),
        CODE_STRUCTURE=sections.get("CODE_STRUCTURE", "Unknown structure"),
        CALL_GRAPH=sections.get("CALL_GRAPH", "No call graph available"),
        INITIAL_SUSPECTS=sections.get("INITIAL_SUSPECTS", "No suspects identified"),
    )


def format_classify_prompt(
    investigation_summary: str,
    node_sections: dict,
) -> str:
    """Format CLASSIFY prompt with investigation context and node details."""
    return CLASSIFY_PROMPT.format(
        INVESTIGATION_SUMMARY=investigation_summary,
        NODE=node_sections.get("NODE", "Unknown"),
        CODE=node_sections.get("CODE", "# No code available"),
        REASON=node_sections.get("REASON", "No reason specified"),
        CALLERS=node_sections.get("CALLERS", "None identified"),
        CALLEES=node_sections.get("CALLEES", "None identified"),
        TEST_COVERAGE=node_sections.get("TEST_COVERAGE", "Unknown"),
        EXISTING_EVIDENCE=node_sections.get("EXISTING_EVIDENCE", "None"),
    )


def format_propose_prompt(
    investigation_summary: str,
    evidence_summary: str,
    frontier: list,
    visited: list,
    queue: list,
) -> str:
    """Format PROPOSE prompt with current state."""
    return PROPOSE_PROMPT.format(
        INVESTIGATION_SUMMARY=investigation_summary,
        EVIDENCE_SUMMARY=evidence_summary,
        FRONTIER=", ".join(frontier) if frontier else "None",
        VISITED=", ".join(visited[:20]) + ("..." if len(visited) > 20 else ""),
        QUEUE="\n".join(f"- {q}" for q in queue[:10]) if queue else "Empty",
    )

