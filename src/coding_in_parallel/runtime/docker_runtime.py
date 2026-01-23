"""Docker-backed runtime for executing commands in a container."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import subprocess
import uuid
from typing import Mapping

from .base import Command, CommandResult


@dataclass
class DockerRuntime:
    """Runtime that executes commands inside a long-lived Docker container."""

    host_repo_path: str
    image: str
    workdir: str = "/repo"
    env: Mapping[str, str] = field(default_factory=dict)
    user: str | None = "host"
    container_name: str = field(default_factory=lambda: f"cip-{uuid.uuid4().hex[:8]}")
    _started: bool = field(default=False, init=False)

    def _resolved_user(self) -> str | None:
        if self.user is None:
            return None
        if self.user != "host":
            return self.user
        try:
            uid = os.getuid()
            gid = os.getgid()
        except AttributeError:
            return None
        return f"{uid}:{gid}"

    def start(self) -> None:
        if self._started:
            return
        if not self.image:
            raise ValueError("Docker runtime requires an image name.")
        host_path = os.path.abspath(self.host_repo_path)
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "-v",
            f"{host_path}:{self.workdir}",
            "-w",
            self.workdir,
        ]
        resolved_user = self._resolved_user()
        if resolved_user:
            cmd.extend(["--user", resolved_user])
        for key, value in self.env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.append(self.image)
        cmd.extend(["sleep", "infinity"])
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "Failed to start Docker container: "
                f"{(proc.stdout + proc.stderr).strip()}"
            )
        self._started = True

    def exec(
        self,
        cmd: Command,
        *,
        timeout_sec: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        self.start()
        docker_cmd = ["docker", "exec", "-w", self.workdir]
        for key, value in (env or {}).items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        docker_cmd.append(self.container_name)
        if isinstance(cmd, str):
            docker_cmd.extend(["/bin/sh", "-lc", cmd])
        else:
            docker_cmd.extend(list(cmd))
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def close(self) -> None:
        if not self._started:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
            text=True,
        )
        self._started = False

    def clone_for_repo(self, repo_path: str) -> "DockerRuntime":
        """Create a new runtime for a different host repo path using same config."""
        return DockerRuntime(
            host_repo_path=repo_path,
            image=self.image,
            workdir=self.workdir,
            env=self.env,
            user=self.user,
        )


__all__ = ["DockerRuntime"]
