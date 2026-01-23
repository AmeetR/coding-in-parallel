install:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv && uv pip install -e .[test]; \
	else \
		python -m venv .venv && . .venv/bin/activate && pip install -e .[test]; \
	fi

uv-install:
	uv venv && uv pip install -e .[test]

run:
	coding-in-parallel --repo $$REPO --task $$TASK --out /tmp/patch.diff --test-cmd "pytest -q"

uv-run:
	uv run coding-in-parallel --repo $$REPO --task $$TASK --out /tmp/patch.diff --test-cmd "pytest -q"

logs:
	@ls -ltr .agent_runs | tail -n 5

lint:
	python -m py_compile $(shell git ls-files '*.py')

uv-lint:
	uv run python -m py_compile $(shell git ls-files '*.py')

test:
	@if command -v uv >/dev/null 2>&1; then \
		uv run pytest; \
	else \
		pytest; \
	fi

uv-test:
	uv run pytest
