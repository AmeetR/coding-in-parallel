"""Runtime abstractions for executing commands."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import subprocess
from typing import Mapping, Protocol, Sequence, Union

Command = Union[str, Sequence[str]]


@dataclass(frozen=True)
class CommandResult:
    """Result of executing a command in a runtime."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runtime(Protocol):
    """Execution runtime interface used by gates and probes."""

    def exec(
        self,
        cmd: Command,
        *,
        timeout_sec: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        ...

    def close(self) -> None:
        ...

    @property
    def workdir(self) -> str:
        ...


class LocalRuntime:
    """Local runtime that shells out on the host."""

    def __init__(self, repo_path: str, *, env: Mapping[str, str] | None = None) -> None:
        self._workdir = repo_path
        self._env = dict(env or {})

    @property
    def workdir(self) -> str:
        return self._workdir

    def exec(
        self,
        cmd: Command,
        *,
        timeout_sec: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        merged_env = os.environ.copy()
        merged_env.update(self._env)
        if env:
            merged_env.update(env)
        if isinstance(cmd, str):
            proc = subprocess.run(
                cmd,
                cwd=self._workdir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=merged_env,
            )
        else:
            proc = subprocess.run(
                list(cmd),
                cwd=self._workdir,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=merged_env,
            )
        return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def close(self) -> None:
        return None

    def clone_for_repo(self, repo_path: str) -> "LocalRuntime":
        return LocalRuntime(repo_path, env=self._env)


__all__ = ["Command", "CommandResult", "LocalRuntime", "Runtime"]
