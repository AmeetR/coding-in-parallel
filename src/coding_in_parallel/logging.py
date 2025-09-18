"""Structured logging utilities for agent runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RunLogger:
    """Persist structured artefacts for a single agent run."""

    def __init__(self, base_dir: str | Path = ".agent_runs", run_id: str | None = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if run_id is None:
            run_id = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = self.base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str, suffix: str) -> Path:
        return self.run_dir / f"{name}.{suffix}"

    def log_json(self, name: str, data: Any) -> Path:
        path = self.path_for(name, "json")
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
        return path

    def log_text(self, name: str, text: str) -> Path:
        path = self.path_for(name, "txt")
        path.write_text(text)
        return path


