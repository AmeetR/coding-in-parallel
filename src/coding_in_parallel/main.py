"""CLI entrypoint for coding-in-parallel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from . import config as config_module, controller, types


def _parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="coding-in-parallel")
    parser.add_argument("--repo", required=True, help="Path to the repository")
    parser.add_argument("--task", required=True, help="Path to SWE-bench task JSON")
    parser.add_argument("--out", required=True, help="Where to write the final patch")
    parser.add_argument("--test-cmd", required=True, help="Command used for targeted tests")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML configuration file (defaults to ./config.yaml if omitted)",
    )
    return parser.parse_args(list(args) if args is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    ns = _parse_args(argv)
    task_data = json.loads(Path(ns.task).read_text())
    ctx = types.TaskContext(
        repo_path=ns.repo,
        failing_tests=list(task_data.get("failing_tests", [])),
        test_cmd=ns.test_cmd or task_data.get("test_cmd", ""),
        targeted_expr=task_data.get("targeted_expr"),
        instance_id=task_data.get("instance_id", "unknown"),
        metadata=task_data.get("metadata", {}),
    )
    cfg = config_module.Config.load(ns.config)
    result = controller.run_controller(ctx, config=cfg)
    Path(ns.out).write_text(result.final_patch)


if __name__ == "__main__":  # pragma: no cover
    main()


