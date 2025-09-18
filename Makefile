install:
python -m venv .venv && . .venv/bin/activate && pip install -e .

run:
swe-fix-agent --repo $$REPO --task $$TASK --out /tmp/patch.diff --test-cmd "pytest -q"

logs:
@ls -ltr .agent_runs | tail -n 5

lint:
python -m py_compile $(shell git ls-files '*.py')
