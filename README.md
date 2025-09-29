# coding-in-parallel

Autonomous, AST-guided bug-fixing with deterministic orchestration and transactional no-regression (TNR) execution. Designed for on-demand evaluation against SWE-bench Verified.

This agent localizes likely fault spans using AST and signals from failing tests, investigates suspects in parallel with read-only probes, plans 2–4 atomic landmarks, proposes small diffs, validates them against strict gates, and commits only if the transaction does not regress. If a candidate fails gates, it is rolled back and the search continues.

## Table of contents

1. Project overview
2. Current status (what’s present vs missing)
3. Architecture and pipeline
4. AST localisation and index
5. Parallel search via read-only branching
6. Investigative probe tools (READ-ONLY)
7. Transaction semantics (TNR)
8. Configuration and runbook (SWE-bench)
9. Evaluation plan
10. Roadmap and milestones
11. Development

## 1) Project overview

`coding-in-parallel` executes a 10-stage algorithm:

1. Localize: Build an AST/call subgraph (2 hops, ≤40 nodes) from failing tests; rank spans using stack traces, tokens, and coverage.
2. Select: Choose 5–7 high-value suspect entities (functions/methods).
3. Probe: Run parallel read-only investigative probes (AST, grep, trace/coverage).
4. Analyze: Each probe outputs structured notes about failure patterns.
5. Combine: Aggregate probe results into a concise failure pattern + candidate fixes.
6. Plan: Decompose into 2–4 atomic landmarks with constraints and ideal outcomes.
7. Propose: Generate K unified diff candidates per landmark, scoped to spans.
8. Validate: Diff validators (LOC, file allowlist, line-range, API/minimality guard).
9. Transact: Checkpoint, apply, gate (static, targeted tests, µ), commit/rollback.
10. Iterate: Move landmark-by-landmark; final patch is the passing, constrained diff.

## 2) Current status

The codebase includes a functional spine for investigation → plan → propose → transact, with AST indexing utilities. Gaps remain around subgraph-based localization, structured probes, and parallelization.

Present

- `ast_index.py`: Builds an AST index of `FunctionDef`/`AsyncFunctionDef`/`ClassDef` and call-sites; provides basic lookups and file slicing.
- `investigator.py`: LLM-driven recall and probe prompts; recalls candidates and enriches with probe output.
- `planner.py`: Synthesizes an understanding and produces plan steps from LLM output.
- `proposer.py`: Produces unified diff candidates, scoped by target spans and context slices.
- `validate.py`: Strong diff validators: unified diff shape, file allowlist, LOC limit, span ±padding line checks.
- `tnr.py`: Transactional execution (checkpoint, apply, static/test gates, µ guard, rollback/commit).
- `vcs.py`: Git helpers (apply diff with fallback hunking, checkpoint/reset, commit, final patch).
- `gates.py`: Static checks via `py_compile`; targeted tests via subprocess.
- `types.py`, `config.py`, `llm.py`, `main.py`, `logging.py`: Datamodels, config, LLM shim, CLI, run logging.

Missing / to be implemented

- Subgraph-based localization (2-hop bounded call/callee graph, ≤40 nodes) and ranking combining stack traces, SBFL/coverage, and token search.
- Agentic suspect selection (5–7) grounded in the AST/call graph and traces.
- Structured probe schema and parallel probe execution; tool adapters (AST slices, grep, trace/coverage) feeding the probe prompts.
- Dedicated planner prompt; constraints/invariants threading; fix `planner.plan` to use a plan-specific template instead of `synthesize.txt`.
- API-compatibility validator and project-specific guards.
- Controller iteration over all plan steps (currently stops after first committed step).
- Read-only branching for parallel search/probe isolation.

## 3) Architecture and pipeline

- Controller (`controller.run_controller`) orchestrates: recall → probe → synthesize → plan → per-step propose → TNR transaction.
- Context slicing is performed around `PlanStep.target_spans` to scope proposer edits.
- TNR gating composes validators, static checks, and targeted tests with rollback on failure.

## 4) AST localisation and index

Implemented

- `ast_index.build_index(repo)`: walks `*.py`, parses with `ast.parse`, records symbol spans (`FunctionDef`, `ClassDef`) and call-sites with `_CallVisitor`. Provides `lookup_symbol`, `lookup_calls`, and `slice(file, start, end, padding)`.

Planned extensions

- Qualified names: index fully-qualified symbols (module/class/function) and imports.
- Call graph: build def→call edges and reverse call edges; expose a bounded subgraph builder `build_call_subgraph(symbols, hops=2, max_nodes=40)`.
- Localize: combine traces, token matches, and coverage/SBFL to rank spans; select 5–7 suspects (unique function/methods) as `AstSpan`s with scores and evidence.

## 5) Parallel search via read-only branching

Goal: execute investigative probes concurrently, each in an isolated, read-only worktree, without permitting code edits. Probes can run tests/coverage and read the repository and AST, but they cannot write code or persist changes to the main worktree.

Design

- Worktree isolation: create detached worktrees per probe (`git worktree add --detach <tmpdir> <HEAD>`). Probes run in these directories.
- Read-only discipline: probes do not run any write-capable commands to source files; they only execute tests/coverage and read artifacts. Any generated artifacts (logs, `.coverage`) are written to the temp worktree and collected by the controller.
- Concurrency: a `ProbePool` schedules N probes concurrently (configurable). Each probe receives its suspect `AstSpan`s, failing tests, and tool handles.
- Lifecycle: worktree created → probe runs tools → results aggregated → worktree removed.

Pseudocode

```text
for suspect in top_suspects:
  worktree = vcs.create_detached_worktree(head)
  submit probe_task(worktree, suspect)
wait for all
combine probe outputs
```

Failure isolation: if a probe crashes or pollutes its worktree, the main repo is unaffected; the worktree is discarded.

## 6) Investigative probe tools (READ-ONLY)

Probes can execute code but cannot write source files. Available tools:

- AST query: `ast_index.lookup_symbol`, `lookup_calls`, `slice(file, start, end, padding)`
- Grep/token search: fast regex/literal search across repo files (read-only)
- Stack trace capture: targeted test run (e.g., `pytest -q -k <test>`), parse trace frames
- Coverage signal: optional run with coverage to obtain line hit data
- File/Module introspection: import-under-test with environment isolation (no writes)
- Metadata readers: `pyproject.toml`, `setup.cfg`, `requirements.txt` (if present)

Explicitly unavailable to probes:

- Any file mutation (no editors, no `git apply/commit`)
- Formatter/linters that rewrite files
- Network calls unless explicitly permitted by config

Probe output schema (enforced):

```json
{
  "assumptions": ["..."],
  "observations": ["..."],
  "failure_pattern": "<=120 words",
  "candidate_fixes": ["..."],
  "risks": ["..."],
  "evidence": { "trace": "...", "grep": ["..."], "coverage": {"file:line": hitCount} }
}
```

## 7) Transaction semantics (TNR)

We adopt Transactional No-Regression (TNR) semantics inspired by [TNR (arXiv:2506.02009)](https://arxiv.org/pdf/2506.02009). A transaction is an atomic attempt to apply one candidate diff for a plan step.

Definitions

- Baseline state: repository at a git checkpoint `HEAD` before applying a candidate.
- µ (churn proxy): average of added/removed lines from `git diff --numstat`.
- Targeted tests: the SWE-bench instance’s failing tests (and optionally a curated subset of related tests).

Transaction procedure

1. Checkpoint: record `HEAD`.
2. Validate: unified diff shape; file allowlist (span files only); LOC ≤ limit; line edits within span ±padding; optional API guard.
3. Apply: attempt `git apply`; fallback to manual hunk application; abort on failure.
4. Gates:
   - Static: `py_compile` over repo (configurable).
   - Tests:
     - If `gates.targeted_tests`: run targeted tests; require they pass post-apply.
   - µ guard: if enabled, require `µ_post ≤ µ_pre` for non-targeted-test mode.
5. Commit or rollback:
   - If all gates pass, `git commit -m "txn:<step-id>"`.
   - Else, hard reset to checkpoint and continue with next candidate.

Ultimate TNR criterion (SWE-bench Verified)

- Success is achieved if the instance’s specified failing test(s) pass post-transaction, without introducing targeted-test regressions, within configured diff limits.

Notes

- Non-targeted baselines may optionally require that a smoke subset remains green.
- All transactions are revertible; no partial commits.

## 8) Configuration and runbook (SWE-bench)

CLI

```bash
coding-in-parallel \
  --repo /path/to/repo \
  --task /path/to/instance.json \
  --out /tmp/patch.diff \
  --test-cmd "pytest -q" \
  --config config.yaml
```

LLM setup

- Provide a client that implements `complete(prompt: str) -> str` and register via `coding_in_parallel.llm.set_client(...)`.
- Example: wrap your model provider and read credentials from environment variables.

Example `config.yaml`

```yaml
model:
  provider: openai
  name: gpt-4o
search:
  max_steps: 3
  diffs_per_step: 3
  finalists: 2
  retries_per_step: 1
limits:
  max_loc_changes: 12
  max_files_per_diff: 2
  slice_padding_lines: 60
tnr:
  actions_per_txn: 3
  require_mu_nonworsening: true
gates:
  static: true
  targeted_tests: true
  smoke: false
logging:
  dir: .agent_runs
```

Runbook (on-demand SWE-bench)

1. Checkout the SWE-bench repository-under-test at the instance commit.
2. Ensure the failing test metadata JSON (instance) is available.
3. Set up your LLM client and `config.yaml`.
4. Run the CLI as above; collect `.agent_runs/*` artifacts and `/tmp/patch.diff`.

References: [SWE-bench](https://github.com/princeton-nlp/SWE-bench) and [SWE-bench website](https://www.swebench.com).

## 9) Evaluation plan

- Dataset: choose 5–10 SWE-bench Verified instances across 3 repos for a smoke eval.
- Metrics: success rate (targeted tests green), LOC/files touched, number of transactions, latency per stage, µ pre/post.
- Criteria: ≥1 success per 5 instances initially; zero targeted-test regressions.
- Logging: persist prompts, LLM responses, diffs, gate outputs in `.agent_runs/<run-id>`.

## 10) Roadmap and milestones

Milestone 1: Controller and planner fixes (quick wins)

- Use a dedicated planner prompt for plan generation; thread constraints and spans.
- Iterate across all plan steps instead of stopping after the first commit.
- Persist run artifacts via `logging.RunLogger`.

Milestone 2: AST subgraph + suspect selection

- Extend `ast_index` with qualified names and call/import graph.
- Implement subgraph builder and ranker; integrate traces, tokens, coverage.
- Select 5–7 suspects and feed to recall/probe prompts and validator allowlists.

Milestone 3: Parallel probes via read-only worktrees

- Add `vcs.create_detached_worktree` + cleanup helpers.
- Implement `ProbePool` with bounded concurrency; collect structured probe outputs.

Milestone 4: Validation hardening and API guards

- Enforce API-compatibility checks; add project-specific guard rails.
- Improve µ to discount whitespace-only changes.

Milestone 5: SWE-bench evaluation & tuning

- Run the on-demand set; iterate limits (`max_loc`, finalists, retries) for stability.

## 11) Development

Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
```

Test

```bash
pytest
```

Run

```bash
coding-in-parallel --help
```

LLM client

Register once before running the agent:

```python
import coding_in_parallel as cip

class MyClient:
    def complete(self, prompt: str, **kwargs):
        # return model output as string
        ...

cip.llm.set_client(MyClient())
```

License: see `LICENSE`.
