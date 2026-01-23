import pytest

from coding_in_parallel.llm_openai import OpenAIClient, make_client_from_env


def test_make_client_from_env_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        make_client_from_env(model_name="gpt-5")


def test_openai_client_parses_output_text():
    def fake_post(url, headers, payload, timeout):
        return {"output_text": "hello"}

    client = OpenAIClient(api_key="key", model_name="gpt-5", _post=fake_post)
    assert client.complete("hi") == "hello"


def test_openai_client_parses_output_messages():
    def fake_post(url, headers, payload, timeout):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "line1"},
                        {"type": "output_text", "text": "line2"},
                    ],
                }
            ]
        }

    client = OpenAIClient(api_key="key", model_name="gpt-5", _post=fake_post)
    assert client.complete("hi") == "line1\nline2"
