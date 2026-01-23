"""Runtime factories and exports."""

from __future__ import annotations

from typing import Optional

from ..config import RuntimeConfig
from .base import Command, CommandResult, LocalRuntime, Runtime
from .docker_runtime import DockerRuntime


def build_runtime(
    cfg: RuntimeConfig,
    repo_path: str,
    *,
    image_override: str | None = None,
) -> Optional[Runtime]:
    """Build a runtime from configuration for the given repository path."""
    kind = (cfg.kind or "local").lower()
    if kind == "local":
        return None
    if kind == "docker":
        image = image_override or cfg.image
        if not image:
            raise ValueError("runtime.image must be set when runtime.kind=docker")
        return DockerRuntime(
            host_repo_path=repo_path,
            image=image,
            workdir=cfg.workdir,
            env=cfg.env,
            user=cfg.user,
        )
    raise ValueError(f"Unsupported runtime kind: {cfg.kind}")


__all__ = [
    "Command",
    "CommandResult",
    "DockerRuntime",
    "LocalRuntime",
    "Runtime",
    "build_runtime",
]
