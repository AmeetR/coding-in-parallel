# coding-in-parallel (feature spec and gap plan)

This repository is a deterministic, AST-guided bug-fixer with Transactional No-Regression (TNR) semantics. It currently ships as a single Python package and CLI; the target is to become:

- `cip-core`: a reusable Python library that exposes graph/AST-guided localization, blackboard-based investigation, planning, proposing, validation, and TNR apply/rollback.
- `cipd`: a daemon/service (HTTP/JSON-RPC + event stream) that owns isolation/worktrees, concurrency, and streaming logs.
- `cip-cli` and `opencode-plugin`: thin clients over `cip-core` or `cipd`.
- Targeted eval shims here (headless SWE-bench runner); full OpenCode-native eval and tooling live in the OpenCode repo to reuse its tools.

This document captures the current state and the detailed change list needed to reach that target.

## Current implementation snapshot

- Orchestrator: `controller.py` runs localize → investigate → combine/plan → propose → validate → TNR. Entry via CLI `coding-in-parallel` (`main.py`).
- Data/model layer: `types.py` for spans, candidates, plans, diffs, and transactions.
- AST index: `ast_index.py` parses Python files, records spans and call sites, and provides slicing helpers.
- Investigations: `investigator.py` with a blackboard, sandboxed probe runner (`probes/runner.py`), scheduler stub (`probes/scheduler.py`), and a simple UCB-like queue. Probes run sequentially for determinism.
- Sandbox/rollback (investigative only): `probes/sandbox.py` applies probe patches in temp dirs and always rolls back.
- Combiner/Planner: `combine.py` and `planner.py` produce failure patterns and landmarks via strict JSON prompts.
- Proposer/Validators: `proposer.py` generates K unified diffs per step; `validate.py` enforces shape, file allowlist, line windows, LOC caps, and a basic API guard.
- Transactional execution: `tnr.py` + `vcs.py` checkpoint, apply, gate (static + targeted tests), µ guard, commit/rollback per candidate. µ is based on `git diff --numstat`.
- Logging/artifacts: `logging.py` writes `.agent_runs/<id>/events.ndjson` plus artifacts (candidates, blackboard, failure_pattern, plan/landmarks, transactions, final_patch).
- LLM integration: `llm.py` shim and optional OpenAI client (`llm_openai.py`) gated by `CIP_USE_OPENAI=1`. Defaults to deterministic/no-network mode for tests.
- Config/test harness: `config.py`, `config.yaml` defaults, `pytest` suite covering modules end-to-end.

## Gaps vs. target design (library + service + TUI)

### Core/library gaps (cip-core)
- Public API surface: No `api.py` exposing `localize`, `investigate`, `plan`, `propose`, `transact`, `fix` with determinism controls (seed, scheduler mode, max_parallelism).
- Evidence/blackboard formalism: Blackboard lacks explicit `(L, P_fwd, P_bwd, frontier, labels, coverage)` ledger with SCC contraction and monotone demotion. No reconciliation helper after each probe/Judge output.
- Graph/context contract: AST index lacks qualified names, reverse edges, bounded K-hop subgraph builder, and stack/token-scored suspect selection. No bounded context-packet builder (K-hop + slices + signals) for Judge prompts.
- Localization scoring: No SBFL/Ochiai; stack/token weighting only partially implied. No “suspect set (5–12) + subgraph + slices” output contract.
- Probes: Minimal read-only probes; lacks instrumentation/assert probes, coverage/trace extraction, and info-gain metrics. Scheduler UCB is stubby and non-concurrent.
- Validators: API guard is basic (functions only). No block/hammock slicing to tighten line windows. No reranker/tiny judge for candidate scoring.
- Determinism controls: No top-level seed or deterministic scheduler mode exposed; parallelism is off by design but not configurable.

### TNR and safety gaps
- Bounded actions per transaction are present (`actions_per_txn`) but not enforced as a public contract. No branch manager for AND/OR hypotheses.
- µ guard exists but is simplistic; no discounting whitespace or weighting by file count.
- No replay API for transactions; no provenance tying evidence to commits.

### Service/daemon gaps (cipd)
- No HTTP/JSON-RPC server; no SSE/NDJSON event stream endpoint.
- No endpoints for `/v1/localize`, `/investigate`, `/plan`, `/propose`, `/txn`, `/fix`, `/txn/replay`, `/events/stream`.
- No worktree/container isolation ownership (only probe temp dirs exist).
- No auth/config overrides per request; no run registry.

### CLI/TUI/OpenCode gaps
- CLI only calls `controller.run_controller` directly; no dual mode (`direct|daemon`).
- No OpenCode plugin (commands `/cip fix|localize|investigate|propose|apply|txn replay|tail`) or tool binding (`cip.fix`) for the main agent.
- No diff picker/apply integration or streamed event rendering.

### Evaluation/SWE-bench gaps
- No thin headless `eval/swebench` shim (`load_instance.py`, `checkout_repo.py`, `run_patch.py`, `verify.py`, `metrics.py`) for direct library/daemon use.
- Full OpenCode-native eval (reusing OpenCode tools) is expected to live in the OpenCode repo; this repo only needs the minimal headless runner.

### Observability and logging gaps
- No opt-in prompt/response logging with redaction/token caps.
- Events lack explicit evidence/frontier/coverage state snapshots per loop.
- No structured schemas for artifacts (Pydantic/TypedDict) to stabilize IO.

### Documentation gaps
- No consolidated API/service docs, endpoint schemas, or OpenCode command reference.
- No guidance on determinism knobs, seeds, and reproducibility.

## Concrete task list to reach the target

1) Library API and schemas  
- Add `api.py` exporting `localize`, `investigate`, `plan`, `propose`, `transact`, `fix` with `Config`/`TaskContext`, determinism controls (seed, scheduler_mode, max_parallelism).  
- Define Pydantic/TypedDict schemas for `LocalizationResult`, `EvidenceState/Ledger`, `FailurePattern`, `LandmarkPlan`, `DiffProposal`, `TransactionResult`, `RunResult`.

2) Evidence/blackboard alignment (EoG-style)  
- Extend blackboard to store `(L, P_fwd, P_bwd, frontier, labels, coverage, suspects, invariants, probe_reports)`.  
- Add `reconcile_evidence(state, graph)` that rebuilds supported graph, contracts SCCs, computes frontier, enforces monotone demotion, labels (Root-Cause/Symptom/Exonerate/Defer), and coverage.  
- Persist ledger snapshots to artifacts; surface state in events.

3) Graph/context contract and localization  
- Add qualified naming and reverse edges to `ast_index`; implement `build_call_subgraph(symbols, hops=K, max_nodes=N)`.  
- Implement localization scoring (stack hits, token matches, optional SBFL/Ochiai placeholder) to return 5–12 suspects + subgraph + slices.  
- Add context-packet builder: K-hop subgraph + slices + stack/token signals + probe artifacts, bounded for Judge prompts.

4) Probes and scheduler  
- Add probe types: read-only (grep/AST/query), instrumentation/assert probes, coverage/trace probes.  
- Compute info_gain per probe; upgrade scheduler UCB; add optional bounded concurrency flag.  
- Keep investigative sandboxes rollback-only; consider git worktree isolation for probes.

5) Planning, proposing, validating  
- Integrate block/hammock slicing (approx SESE) for tighter edit windows; expose in validators.  
- Harden API guard for methods, decorators, async, kw-only/pos-only params; add optional `allow_api` override.  
- Add reranker/tiny judge hook for candidate scoring.

6) TNR enhancements  
- Enforce `actions_per_txn` as a hard cap; expose µ weighting (discount whitespace, weight files).  
- Add branch manager stub for AND/OR hypotheses orchestration.  
- Add transaction replay helper and provenance tying evidence → plan step → commit.

7) Service/daemon (`cipd`)  
- Build HTTP/JSON endpoints: `/v1/localize`, `/investigate`, `/plan`, `/propose`, `/txn`, `/fix`, `/txn/replay`.  
- Add SSE/NDJSON stream endpoint `/v1/events/stream?run_id=...`.  
- Own worktree/container isolation, run registry, config overrides per request, auth stub.

8) CLI/TUI/OpenCode integration  
- Add `cip` CLI with `--mode direct|daemon`; commands: `fix`, `localize`, `investigate`, `txn`, `replay`.  
- Sketch OpenCode plugin commands `/cip fix|localize|investigate|propose|apply|txn replay|tail` and tool `cip.fix` binding to `cipd`.  
- Add simple diff picker/apply flow (client-side) and event stream tailer.

9) SWE-bench adapter and evaluation  
- Add a thin `eval/swebench` shim here (loaders, checkout helper, patch runner, verifier, metrics) for headless runs against `cip-core`/`cipd`.  
- Document that full OpenCode eval lives in the OpenCode repo (reusing OpenCode tools); keep this repo’s eval surface minimal.

10) Observability/logging  
- Add opt-in prompt/response logging with redaction and token caps.  
- Emit evidence/frontier/coverage snapshots in events; version events/artifacts schema.  
- Add run metadata (seed, config hash, commit hash) for reproducibility.

11) Testing and determinism  
- Add seeds to schedulers and proposer ordering; expose deterministic mode in config.  
- Expand tests for new API guard cases, block slicing validators, localization scoring, daemon endpoints, and replay.

12) Docs  
- Update docs with API reference, service endpoints, OpenCode commands, determinism guidance, and safety/TNR explanation.

## Development quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pytest
coding-in-parallel --help
```

LLM client (optional):

```python
import coding_in_parallel as cip
cip.llm.set_client(...)
```

License: see `LICENSE`.
