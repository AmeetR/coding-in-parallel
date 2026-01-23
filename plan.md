# Execution Plan (SWE-bench First)

## Goal
Deliver a runnable end‑to‑end SWE‑bench evaluation path first (Lite), then expand to full SWE‑bench, then OpenCode integration. This plan is grounded in the current codebase state and enumerates concrete issues to fix.

---

## Current Repo Issues (Code‑Grounded)

### 1) LLM integration is required but not safely optional
- `llm.complete()` raises by default; core pipeline depends on it. `src/coding_in_parallel/llm.py`
- `main.py` attempts to import `llm_openai` when `CIP_USE_OPENAI=1`, but `llm_openai` does not exist. `src/coding_in_parallel/main.py`

### 2) Graph‑guided agent is inconsistent with actual APIs
- `agents/localization.py` imports `ASTIndex` and uses `lookup_qualname`, neither exists. `src/coding_in_parallel/agents/localization.py`, `src/coding_in_parallel/ast_index.py`
- Calls `localize.localize` with wrong parameter names, and expects fields not present on `types_localize.Suspect` and `trace_parser.StackFrame`. `src/coding_in_parallel/agents/localization.py`, `src/coding_in_parallel/localize.py`, `src/coding_in_parallel/types_localize.py`, `src/coding_in_parallel/trace_parser.py`
- Expects `build_call_subgraph` to return dicts; it returns `(nodes, edges)`. `src/coding_in_parallel/agents/localization.py`, `src/coding_in_parallel/ast_index.py`

### 3) Localization path has partial stubs and correctness gaps
- Subgraph edges and hammocks are stubbed. `src/coding_in_parallel/localize.py`
- Token hit evidence for an existing suspect is dropped due to frozen dataclass and `pass`. `src/coding_in_parallel/localize.py`
- Method detection is incorrect (checks for `.` in `span.symbol`). `src/coding_in_parallel/localize.py`

### 4) Investigations / probes are stubbed or broken
- Probe patch format is malformed (no hunk ranges), so `git apply` likely fails. `src/coding_in_parallel/investigator.py`, `src/coding_in_parallel/probes/sandbox.py`
- Probe runner never stores `info_gain` in artifacts; `total_gain` always defaults. `src/coding_in_parallel/probes/runner.py`
- Blackboard and scheduler are explicitly stubbed. `src/coding_in_parallel/probes/blackboard.py`, `src/coding_in_parallel/probes/scheduler.py`

### 5) Landmarks path can’t run end‑to‑end
- `plan_landmarks` references a missing prompt file (`plan_landmarks.txt`). `src/coding_in_parallel/planner.py`, `prompts/`
- `combine_to_failure_pattern` produces dict spans; `plan_landmarks` expects dataclass spans. `src/coding_in_parallel/combine.py`, `src/coding_in_parallel/planner.py`

### 6) VCS fallback apply is unsafe
- `_manual_apply` ignores hunk ranges/context; can misapply changes. `src/coding_in_parallel/vcs.py`

### 7) Tests fail by default
- `tests/fixtures/test_failing_example.py` is intentionally failing and is collected by pytest. `tests/fixtures/test_failing_example.py`, `pytest.ini`

### 8) SWE‑bench run path is incomplete
- No predictions JSONL writer; no dataset‑level harness integration. `src/coding_in_parallel/main.py`, `README.md`
- `coding-in-parallel solve` CLI in README is not implemented (current CLI expects `--task` JSON with failing tests and test_cmd). `README.md`, `src/coding_in_parallel/main.py`

---

## Milestone 1 (Primary): SWE‑bench Lite evaluation is runnable

### M1.1 – Define the minimal runnable CLI for SWE‑bench
**Goal:** A CLI that reads SWE‑bench task JSON, generates a patch (even baseline/no‑op), and writes predictions JSONL.
- Add a `solve` entry path that reads SWE‑bench task schema, sets up `TaskContext`, and produces a patch file.
- Add a `predict`/`batch` entry path that consumes a list of SWE‑bench tasks and emits JSONL in required format.
- Ensure output conforms to:
  ```json
  {"instance_id": "...", "model_name_or_path": "...", "model_patch": "diff --git ..."}
  ```

### M1.2 – Make LLM integration robust and required
**Goal:** LLM‑backed reasoning is mandatory; make client setup reliable and failure modes explicit.
- Implement provider adapter(s) (e.g., `llm_openai.py`) so `CIP_USE_OPENAI=1` works end‑to‑end.
- Validate env/config at startup and fail fast with a clear, actionable error if no LLM client is configured.
- Centralize model/provider selection (config + env overrides) so runs are reproducible.

### M1.3 – README‑aligned localization/investigation MVP (AST + explore/exploit)
**Goal:** The eval harness uses the actual architecture: AST‑guided localization, bounded subgraph, explore/exploit probes, and TNR.
- Wire `controller` to use the LangGraph localization agent (BASELINE → SELECT → CLASSIFY → RECONCILE → PROPOSE) instead of the LLM‑only recall path.
- Make `agents/localization.py` consistent with real APIs (`ast_index`, `localize`, `trace_parser`, `types_localize`) and remove placeholder mismatches.
- Implement bounded subgraph edges from `ast_index.build_call_subgraph` and surface them in `SupportedSubgraph`.
- Implement **Hammock Stage A** (AST block regions) to produce edit windows and use them in validation allowlists.
- Fix token evidence merge for existing suspects and correct method classification.
- Ensure explore/exploit probes are runnable end‑to‑end (valid probe patch hunks, meaningful `info_gain`, blackboard/ledger updates).

### M1.4 – Docker‑based SWE‑bench prerequisites (mandatory)
**Goal:** Ensure the Docker evaluation harness is ready and reproducible.
- Document and enforce Docker requirement (SWE‑bench evaluation requires Docker; no non‑Docker path).
- Add a repo checklist for Docker readiness: `docker --version`, `docker run hello-world`, `docker system df`.
- Record minimum resources and platform guidance: ≥120GB free disk, ≥16GB RAM, 8 CPU cores recommended; x86_64 preferred, arm64 experimental.
- For Docker Desktop: allocate at least 8 CPUs, 16GB RAM, and ≥120GB disk image size.
- Capture cache policy from SWE‑bench docs: `none|base|env|instance` (default `env`); prefer `--cache_level env` and `--clean True` for disk‑constrained runs.
- Record worker guidance: `max_workers < min(0.75 * os.cpu_count(), 24)` (e.g., 8 cores → 6, 16 cores → 12).
- Add ARM/M‑series note: use `--namespace ''` when running eval to build images locally (optional but documented).

### M1.5 – Make pytest green (required for confidence)
**Goal:** Default `pytest` runs do not fail.
- Exclude intentionally failing fixtures with `pytest.ini` (`testpaths` or `-k "not failing_example"`) or mark tests and skip by default.

### M1.6 – SWE‑bench harness dry run (Docker path)
**Goal:** Run `swebench.harness.run_evaluation` successfully against a small predictions file.
- Add a `docs/` or `scripts/` recipe to produce predictions JSONL.
- Validate with SWE‑bench Lite using:
  ```bash
  python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Lite \
    --predictions_path <preds.jsonl> \
    --max_workers 8 \
    --run_id cip_lite_smoke
  ```
- Add a harness sanity check using gold patches:
  ```bash
  python -m swebench.harness.run_evaluation \
    --predictions_path gold \
    --max_workers 1 \
    --instance_ids sympy__sympy-20590 \
    --run_id validate-gold
  ```
- Capture evaluation outputs path and files (`evaluation_results/<run_id>/results.json`, `instance_results.jsonl`, `run_logs/`).
- Note docker build logs in `logs/build_images` and run logs in `logs/run_evaluation`.

**Exit Criteria:**
- `coding-in-parallel` can emit a valid JSONL predictions file.
- SWE‑bench Lite evaluation starts and completes via Docker without CLI/runtime errors.
- Localization/investigation path used in the run is the README architecture (AST + subgraph + explore/exploit + TNR).

---

## Milestone 2: End‑to‑end correctness improvements (LLM‑required)

### M2.1 – Improve fallback planning & patching heuristics
- Add a minimal deterministic proposer that can produce a no‑op patch or targeted micro‑diff for simple cases (e.g., change a single return expression).
- Ensure `validate.ensure_within_limits` is invoked on all proposals.

### M2.2 – Fix investigations path enough for deterministic use
- Repair probe patch generation so `git apply` succeeds.
- Fix `info_gain` propagation in probe runner.
- Leave scheduler/blackboard as stubs but make output stable and non‑crashing.

### M2.3 – Harden VCS apply fallback
- Either remove `_manual_apply` or constrain it to simple single‑hunk cases with strict checks.

**Exit Criteria:**
- Controller completes a run with a configured LLM.
- Probes and TNR do not crash in the standard (LLM‑enabled) pipeline.

---

## Milestone 3: SWE‑bench coverage and scaling

### M3.1 – Batch prediction generation
- Implement a batch runner that accepts a list of SWE‑bench instances (or HF dataset) and writes predictions JSONL.
- Add rate controls and deterministic logging to `.agent_runs`.

### M3.2 – Eval tooling
- Add helper scripts for:
  - Lite vs full SWE‑bench
  - Targeted instance runs (`--instance_ids`)
  - Cache policy and cleanup (`--cache_level`, `--clean`)

**Exit Criteria:**
- Full dataset evaluation can run (even if low score), with reproducible logs.

---

## Milestone 4: LLM integration (agent upgrade)

### M4.1 – Implement LLM client adapters
- Add `llm_openai.py` or new provider adapters.
- Keep `CIP_USE_OPENAI=1` and `OPENAI_MODEL` gating intact.

### M4.2 – Integrate prompts with the localization agent
- Wire `agents/localization.py` to actual `ast_index`/`localize` outputs.
- Replace placeholder LLM calls with prompt templates in `agents/prompts.py`.

**Exit Criteria:**
- LLM‑powered localization can run on a single SWE‑bench instance.

---

## Milestone 5: OpenCode integration

### M5.1 – MCP server interface (primary)
- Implement a local MCP server for `coding-in-parallel` (stdio or SSE) so OpenCode can discover tools.
- Publish tool methods (`diagnose`, `solve`, `apply_patch`) and keep outputs bounded.
- Provide OpenCode config snippet under `mcp` to register the server and per‑agent tool enablement.
- Include MCP caveat: each MCP server adds context tokens; be selective about enabling servers.

### M5.2 – OpenCode agent + permissions config
- Provide an `opencode.json` / `opencode.jsonc` example configuring a dedicated agent with scoped tools and permissions.
- Use per‑agent MCP enablement (disable globally with glob, enable per agent), and explicit permissions (`allow`/`ask`/`deny`).
- Document that `permission` is the preferred control surface (legacy `tools` booleans are deprecated but supported).
- Document MCP configuration for local and remote servers (`type: local` with `command`/`environment`; `type: remote` with `url`/`headers`).
- Document config precedence (remote defaults → global `~/.config/opencode/opencode.json` → `OPENCODE_CONFIG` → project `opencode.json` → `.opencode` dirs → `OPENCODE_CONFIG_CONTENT`).

### M5.3 – Optional OpenCode server integration
- Document `opencode serve` (port/hostname/mdns/cors) and the `/doc` OpenAPI endpoint for programmatic control.
- Include server auth environment variables (`OPENCODE_SERVER_PASSWORD`, optional `OPENCODE_SERVER_USERNAME`).

**Exit Criteria:**
- OpenCode can call the tool server to run a solve.

---

## Immediate Next Actions (Start Here)
1) Add minimal SWE‑bench CLI/predictions JSONL writer.
2) Implement required LLM adapter(s) and fix `llm_openai` import failure.
3) Fix localization token evidence merge + method detection.
4) Exclude intentionally failing fixtures from default pytest.
5) Run SWE‑bench Lite evaluation with a smoke predictions file.
