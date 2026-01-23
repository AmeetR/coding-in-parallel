import json
import os
from pathlib import Path
import subprocess

import pytest

from coding_in_parallel import main


class DummyClient:
    def complete(self, prompt: str, **_: object) -> str:
        # ast_recall
        if "Return JSON ONLY" in prompt:
            return json.dumps(
                {
                    "candidates": [
                        {
                            "id": "cand-1",
                            "hypothesis": "add subtracts",
                            "spans": [
                                {
                                    "file": "mod.py",
                                    "start_line": 1,
                                    "end_line": 2,
                                    "node_type": "FunctionDef",
                                    "symbol": "add",
                                    "score": 0.9,
                                }
                            ],
                        }
                    ]
                }
            )
        # synthesize
        if "synthesize" in prompt.lower():
            return json.dumps(
                {
                    "summary": "Fix add",
                    "invariants": [],
                    "dependencies": [],
                }
            )
        # plan
        if "Generate a structured plan as JSON array" in prompt:
            return json.dumps(
                [
                    {
                        "id": "step-1",
                        "intent": "Fix add",
                        "target_spans": [
                            {
                                "file": "mod.py",
                                "start_line": 1,
                                "end_line": 2,
                                "node_type": "FunctionDef",
                            }
                        ],
                        "constraints": [],
                        "ideal_outcome": "add returns sum",
                        "check": "tests",
                    }
                ]
            )
        # propose_diff
        if "unified_diff" in prompt and "Output JSON ONLY" in prompt:
            return json.dumps(
                [
                    {
                        "step_id": "step-1",
                        "unified_diff": "diff --git a/mod.py b/mod.py\n@@ -1,2 +1,2 @@\n-def add(x, y):\n-    return x - y\n+def add(x, y):\n+    return x + y\n",
                        "rationale": "fix",
                    }
                ]
            )
        # probe
        if "probe" in prompt.lower():
            return json.dumps({"notes": "ok"})
        # baseline/classify/propose for LangGraph (should not be used here)
        if "Node Under Investigation" in prompt:
            return json.dumps({"label": "suspect", "confidence": 0.5, "evidence": []})
        if "deciding next steps" in prompt:
            return json.dumps({"action": "conclude", "candidates": [], "probes": [], "conclusion_reason": "done"})
        return "summary"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "mod.py").write_text("def add(x, y):\n    return x - y\n")
    subprocess.run(["git", "add", "mod.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_end_to_end_smoke_with_openai_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    instance = {
        "instance_id": "example-1",
        "test_cmd": "pytest -k add",
        "failing_tests": ["tests/test_mod.py::test_add"],
    }
    instance_path = tmp_path / "instance.json"
    instance_path.write_text(json.dumps(instance))
    output_path = tmp_path / "patch.diff"
    preds_path = tmp_path / "preds.jsonl"

    # Minimal config: disable langgraph for this smoke test
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "model:\n  provider: \"openai\"\n  name: \"gpt-5\"\n"
        "search:\n  use_langgraph: false\n  investigations_enabled: false\n  use_landmarks: false\n"
    )

    # Force OpenAI adapter path, but return a dummy client
    monkeypatch.setenv("CIP_USE_OPENAI", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    import coding_in_parallel.llm_openai as llm_openai

    monkeypatch.setattr(llm_openai, "make_client_from_env", lambda model_name=None: DummyClient())

    # Avoid running real tests
    from coding_in_parallel import gates
    monkeypatch.setattr(gates, "run_static_checks", lambda repo_path, runtime=None: (True, "ok"))
    monkeypatch.setattr(gates, "run_targeted_tests", lambda cmd, repo_path, runtime=None: (True, "ok"))

    main.main([
        "--repo",
        str(repo),
        "--task",
        str(instance_path),
        "--out",
        str(output_path),
        "--test-cmd",
        "pytest -k add",
        "--predictions-out",
        str(preds_path),
        "--config",
        str(cfg_path),
    ])

    assert output_path.read_text().startswith("diff --git")
    assert preds_path.read_text().strip()
