"""OpenAI REST client adapter for coding-in-parallel.

This adapter uses the Responses API via HTTPS requests and returns
aggregated text output for the prompt.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from . import llm


PostFn = Callable[[str, Dict[str, str], Dict[str, Any], int], Dict[str, Any]]


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(f"OpenAI HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned non-JSON response: {body[:200]}") from exc


@dataclass
class OpenAIClient:
    api_key: str
    model_name: str
    base_url: str = "https://api.openai.com/v1"
    organization: Optional[str] = None
    project: Optional[str] = None
    timeout_sec: int = 60
    _post: PostFn = _post_json

    def complete(self, prompt: str, **kwargs: Any) -> str:
        url = self.base_url.rstrip("/") + "/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "input": prompt,
        }
        # Allow caller overrides for common params (temperature, max_output_tokens, response_format, etc.)
        payload.update(kwargs)

        response = self._post(url, headers, payload, self.timeout_sec)
        return _extract_output_text(response)


def _extract_output_text(response: Dict[str, Any]) -> str:
    if isinstance(response, dict):
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        outputs = response.get("output", [])
        texts: list[str] = []
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []) or []:
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") in {"output_text", "text"}:
                        text = content.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
        if texts:
            return "\n".join(texts)
    return json.dumps(response, ensure_ascii=False)


def make_client_from_env(model_name: Optional[str] = None) -> llm.SupportsComplete:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to use the OpenAI client.")
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    org = os.environ.get("OPENAI_ORGANIZATION")
    project = os.environ.get("OPENAI_PROJECT")
    model = model_name or os.environ.get("OPENAI_MODEL") or "gpt-5"
    return OpenAIClient(
        api_key=api_key,
        model_name=model,
        base_url=base_url,
        organization=org,
        project=project,
    )


__all__ = ["OpenAIClient", "make_client_from_env"]
