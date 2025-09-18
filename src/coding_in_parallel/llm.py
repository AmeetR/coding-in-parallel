"""LLM provider shim used throughout the agent."""

from __future__ import annotations

from typing import Any, Protocol


class SupportsComplete(Protocol):
    def complete(self, prompt: str, **kwargs: Any) -> str:  # pragma: no cover - protocol
        ...


class _DefaultClient:
    def complete(self, prompt: str, **_: Any) -> str:
        raise RuntimeError(
            "No LLM client configured. Call coding_in_parallel.llm.set_client() before use."
        )


_client: SupportsComplete = _DefaultClient()


def set_client(client: SupportsComplete) -> None:
    """Register a global client used by :func:`complete`."""

    global _client
    _client = client


def complete(prompt: str, **kwargs: Any) -> str:
    """Delegate to the configured LLM client."""

    return _client.complete(prompt, **kwargs)


