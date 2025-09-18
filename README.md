# coding-in-parallel

`coding-in-parallel` is an implementation of a bug fixing agent that attempts to break bug fixing (or in the future feature development) by using AST to localize potential fix locations, then reasoning in parallel to investigate each of those. Once that is complete, it will put together to create a plan of action of resolution, which will then use gated transactions. If a potential change is made and does not pass quality gates, it is reverted and attempt to rewrite. It focuses on deterministic orchestration for SWE-bench Verified tasks,
including AST-guided localisation, planning, diff synthesis, and transactional execution with
git-based rollbacks.

## Features

- Python-only pipeline with prompt-driven investigation and planning phases.
- Transactional execution (TNR) with static checks and targeted test gates.
- Structured run logging and reproducible configuration via `config.yaml`.

## Development

Create a virtual environment and install the project in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
```

Run the test suite with `pytest`:

```bash
pytest
```

### Running the agent

The CLI entrypoint `coding-in-parallel` can be invoked manually once configured with a
SWE-bench instance JSON and repository checkout. The configuration file defaults to
`./config.yaml`, but you can supply an alternative path with `--config`:

```bash
coding-in-parallel \
  --repo /path/to/repo \
  --task /path/to/instance.json \
  --out /tmp/patch.diff \
  --test-cmd "pytest -q" \
  --config config.yaml
```

Model providers require credentials. For the default OpenAI configuration, export:

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_API_BASE="https://api.openai.com/v1"  # optional override
```

Then provide a client implementation that consumes these variables via
`coding_in_parallel.llm.set_client(...)` before running the agent.

