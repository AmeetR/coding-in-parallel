"""Structured logging utilities for agent runs.

Adds both artifact persistence and lightweight streaming of events.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


class RunLogger:
    """Persist structured artefacts for a single agent run."""

    def __init__(self, base_dir: str | Path = ".agent_runs", run_id: str | None = None, *, stream: bool | None = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if run_id is None:
            run_id = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = self.base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # Event stream config (env var override)
        if stream is None:
            stream = _truthy(os.environ.get("CIP_LOG_STREAM"))
        self._stream = bool(stream)
        self._events_path = self.run_dir / "events.ndjson"

    def path_for(self, name: str, suffix: str) -> Path:
        return self.run_dir / f"{name}.{suffix}"

    def log_json(self, name: str, data: Any) -> Path:
        path = self.path_for(name, "json")
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
        self.log_event("file.write", name=name, path=str(path))
        return path

    def log_text(self, name: str, text: str) -> Path:
        path = self.path_for(name, "txt")
        path.write_text(text)
        self.log_event("file.write", name=name, path=str(path))
        return path

    def log_event(self, kind: str, /, **data: Any) -> None:
        """Append a structured event to events.ndjson and optionally echo to stdout."""
        record = {
            "ts": time.time(),
            "ts_iso": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "kind": kind,
            "data": data,
        }
        # Append as one JSON line
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        if self._stream:
            # Compact human-readable echo
            msg = f"[{record['ts_iso']}] {kind} "
            # include a couple of common fields if present
            for key in ("step_id", "intent", "committed"):
                if key in data:
                    msg += f"{key}={data[key]} "
            print(msg.strip(), file=sys.stdout, flush=True)

