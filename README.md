# coding-in-parallel

`coding-in-parallel` is a reference implementation of the SWE Fix Agent described in the
project specification. It focuses on deterministic orchestration for SWE-bench Verified tasks,
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

The CLI entrypoint `coding-in-parallel` can be invoked manually once configured with a
SWE-bench instance JSON and repository checkout.

