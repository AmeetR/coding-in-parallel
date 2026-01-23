# Localization and Suspect Discovery (Spec)

This document defines the localization subsystem: an EoG-inspired (Explanations-over-Graphs) agentic architecture that discovers fault locations through iterative, LLM-guided investigation over bounded context packets.

## Overview

The localization agent runs a two-phase process:

1. **BASELINE**: Gather all available context, build a mental model, create an investigation summary
2. **EXPLORE-AND-JUDGE**: Iteratively investigate nodes with bounded context, classify origin/propagation, propose probes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     LOCALIZATION AGENT (LangGraph)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  START ──▶ BASELINE ──▶ SHOULD_CONTINUE? ──▶ SELECT ──▶ CLASSIFY            │
│                              │                              │                │
│                              │ done                         ▼                │
│                              │                          RECONCILE            │
│                              ▼                              │                │
│                            END ◀── PROPOSE ◀────────────────┘                │
│                                       │                                      │
│                                       └──────▶ SHOULD_CONTINUE?              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Architecture Components

### Controller (Deterministic)
- Manages global state: Evidence Ledger, exploration queue, causal graph
- Executes all external I/O through Context Contract
- Performs deterministic reconciliation after each Judge output
- Never reasons; only bookkeeps

### LLM Judge (Bounded Reasoning)
- Analyzes fixed-scope context packets
- Emits structured judgments: L(v), P(u→v), rationale
- Can request probes (targeted tests) for more evidence
- Never calls tools directly; never sees unbounded context

### Context Contract (CxC)
- Guarantees bounded context for every Judge invocation
- BASELINE: K-hop subgraph from failing tests, all initial signals
- CLASSIFY: Per-node CFG, callers/callees, data flow, coverage

---

## Phase 1: BASELINE

**Goal:** Understand the problem space. Build a mental model. Create hypotheses.

### Inputs

- `TaskContext`: `repo_path`, `failing_tests`, `test_cmd`, `instance_id`, `metadata`
- `test_output`: Raw pytest stderr/stdout with stack traces

### Context Gathered

| Category | Data | Source |
|----------|------|--------|
| **Error Analysis** | Error type, message, assertion strings | `trace_parser.py` |
| **Stack Trace** | `(file, line, function)` frames | `trace_parser.py` |
| **K-hop Subgraph** | Call paths from failing tests into codebase | `ast_index.build_call_subgraph()` |
| **Package Structure** | Module tree, import graph | `ast_index.py` |
| **Initial Suspects** | Ranked by stack hits, token matches, heuristics | `localize.py` |
| **Code Slices** | Numbered snippets around suspects | `ast_index.slice_numbered()` |
| **Git Context** | Recent changes, blame for suspect lines | `git blame`, `git log` |
| **Test Context** | Test file overview, test-to-module links | Heuristic extraction |
| **Type Information** | Function signatures, docstrings | `ast` module |

### Output

- `investigation_summary`: LLM-generated analysis with hypotheses
- `ledger`: Initial evidence state (all suspects L=2/Defer)
- `queue`: Top suspects to investigate first

### BASELINE Prompt Structure

```
## Error Information
- Error: {error_type}: {error_message}
- Failing Tests: {failing_tests}

## Stack Trace
{formatted_frames}

## Call Graph (K-hop from failing tests)
test_calculate_sum_basic
  └── calculate_sum (calculator.py:5)  ← SUSPECT
        └── (leaf)

## Package Structure
{module_tree}

## Initial Suspects (ranked)
1. calculate_sum - Score 1.0 - "Appears in stack trace"
2. helper_function - Score 0.7 - "Calls calculate_sum"

## Recent Git Changes
{blame_info}

## Code Snippets
{slices}

---
Create an INVESTIGATION SUMMARY:
1. Failure Hypothesis
2. Primary Suspects (2-3) with reasoning
3. Propagation Theory
4. Investigation Strategy
```

---

## Phase 2: EXPLORE-AND-JUDGE Loop

**Goal:** Iteratively investigate nodes. Classify origin vs symptom. Build causal graph.

### Evidence Ledger

```python
@dataclass
class EvidenceLedger:
    # Local origin evidence: L(v) ∈ {0=exonerated, 1=origin, 2=defer}
    L: Dict[str, int]
    
    # Propagation evidence: P(u→v) ∈ {0, 1}
    P_fwd: Dict[Tuple[str, str], int]
    P_bwd: Dict[Tuple[str, str], int]
    
    # Derived
    G_S: Set[Tuple[str, str]]  # Supported causal graph
    frontier: Set[str]  # Root cause candidates
    labels: Dict[str, str]  # RC, Symptom, Exonerate, Defer
    
    # Audit
    rationales: List[Dict]
```

### Per-Node Context Packet (CLASSIFY)

| Category | Data | Purpose |
|----------|------|---------|
| **Investigation Summary** | From BASELINE | Continuity across steps |
| **Code Slice** | Function with line numbers | See the code |
| **CFG** | Control flow graph (blocks, branches) | Understand logic flow |
| **Callers** | Who calls this, with their code | Upstream context |
| **Callees** | What this calls, with their code | Downstream context |
| **Data Flow** | Parameters → return value | What flows where |
| **Test Coverage** | Lines hit by tests | Coverage gaps |
| **Related Tests** | Tests that exercise this function | Test context |
| **Ledger State** | Current L, P, frontier | What we know so far |

### CLASSIFY Output

```json
{
    "L": 0|1|2,
    "P": {"caller_id": 0|1, ...},
    "rationale": "...",
    "probe_request": null | {
        "type": "targeted_test",
        "code": "def test_hypothesis(): ...",
        "hypothesis": "Check if calculate_sum handles negatives"
    }
}
```

### RECONCILE (Controller, Deterministic)

1. Merge bits: `S ← S ∪ ΔS`
2. Build causal graph: `G_S ← edges where P=1`
3. Contract SCCs (handle cycles)
4. Compute frontier: origin nodes with no upstream origins
5. Assign labels: Root-Cause, Symptom, Exonerate, Defer
6. Enforce monotone demotion (no label flapping)

### PROPOSE (LLM Judge)

Suggest next nodes based on:
- Upstream neighbors of Symptoms lacking known origin
- Nodes adjacent to Defer cases
- Coverage gaps (alerts not reachable from frontier)

---

## Probes: Targeted Test Writing

The bounded Judge can request probes to gather more evidence:

| Probe Type | Description | Example |
|------------|-------------|---------|
| **Targeted Test** | Write a test to check hypothesis | `assert calculate_sum(5,3) == 8` |
| **Instrumentation** | Add prints/logging, re-run | `print(f"a={a}, b={b}, result={a-b}")` |
| **Assertion Check** | Test specific invariant | `assert isinstance(result, int)` |
| **Input Variation** | Test edge cases | `calculate_sum(-1, -1)` |

Probes run in sandbox. Results feed back as observability data for next iteration.

---

## Termination Conditions

1. **Coverage satisfied**: Frontier covers all alerts via supported paths
2. **Queue empty**: No more nodes to investigate
3. **Budget exhausted**: Max iterations reached

---

## Output: LocalizationResult

```python
@dataclass
class LocalizationResult:
    suspects: List[Suspect]           # Ranked, with reasons
    subgraph: SupportedSubgraph       # Nodes + causal edges
    slices: Dict[str, List[Slice]]    # Code snippets for prompts
    hammocks: Dict[str, List[Block]]  # Edit windows
    ledger: EvidenceLedger            # Final evidence state
    investigation_summary: str        # For remediation handoff
    
    def reasons_for_remediation(self) -> Dict[str, List[str]]:
        """Return suspect_id → list of reasons."""
```

---

## Suspect Definition

```json
{
  "id": "sus-<hash>",
  "file": "pkg/module.py",
  "span": {"start_line": 120, "end_line": 167},
  "kind": "function|method|class|module",
  "qualname": "pkg.module.ClassName.method",
  "symbol": "method",
  "reason": "Appears in stack trace at line 125",
  "anchors": {"def_line": 120, "signature": "def method(self, x):"},
  "evidence": {
    "items": [
      {"kind": "stack_hit", "source": "traceback:125", "reason": "...", "weight": 1.0},
      {"kind": "token_hit", "source": "grep:calculate_sum", "reason": "...", "weight": 0.7}
    ],
    "stack_hits": [...],
    "token_hits": [...],
    "callgraph_hops_from_stack": 1
  },
  "score": 0.83
}
```

---

## Handoff to Remediation

Remediation receives:

- **Investigation Summary**: LLM-generated understanding of the problem
- **Ranked Suspects**: With stable IDs, reasons, evidence
- **Causal Graph**: Propagation edges showing fault flow
- **Code Slices**: Numbered snippets for prompts
- **Ledger**: Labels (RC/Symptom/Exonerate) for each node

The remediation phase uses this to:
1. Target edits at Root-Cause nodes
2. Validate that changes don't break Symptom propagation
3. Understand the fix in context of the causal chain

---

## Implementation Modules

| Module | Purpose |
|--------|---------|
| `trace_parser.py` | Parse stack traces, extract (file, line) frames |
| `token_search.py` | Find error strings in source code |
| `ast_index.py` | Qualnames, callers/callees, K-hop subgraph |
| `cfg_builder.py` | Control flow graph per function |
| `localize.py` | BASELINE context gathering |
| `agents/localization.py` | LangGraph agent with BASELINE, CLASSIFY, RECONCILE, PROPOSE |
| `probes/` | Sandbox, runner, scheduler for targeted tests |
| `types_localize.py` | Suspect, Evidence, Ledger types |
