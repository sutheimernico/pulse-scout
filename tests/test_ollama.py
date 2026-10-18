"""Tests for the model seam. None of these reach the network."""

from __future__ import annotations

import json

import pytest

from pulse_scout.llm.ollama import OllamaClient, OllamaError
from tests.fakes import scripted_transport

GENERATE_OK = {
    "model": "qwen2.5:1.5b",
    "response": "7\nrelevant to his backend stack",
    "done": True,
    "done_reason": "stop",
    "total_duration": 2_000_000_000,
    "load_duration": 300_000_000,
    "prompt_eval_count": 362,
    "prompt_eval_duration": 1_000_000_000,
    "eval_count": 18,
    "eval_duration": 500_000_000,
}


def client(payloads) -> tuple[OllamaClient, object]:
    transport = scripted_transport(payloads)
    return OllamaClient(host="http://ollama.test", transport=transport), transport


def test_generate_returns_text_and_timings() -> None:
    api, _ = client([GENERATE_OK])
    completion = api.generate(model="qwen2.5:1.5b", prompt="rate this")

    assert completion.text.startswith("7")
    assert completion.prompt_tokens == 362
    assert completion.output_tokens == 18
    # Ollama reports nanoseconds; the seam converts once, at the edge.
    assert completion.prompt_seconds == pytest.approx(1.0)
    assert completion.output_seconds == pytest.approx(0.5)
    assert completion.prompt_tokens_per_second == pytest.approx(362.0)
    assert completion.output_tokens_per_second == pytest.approx(36.0)
    assert completion.truncated is False


def test_generate_sends_system_and_options() -> None:
    api, transport = client([GENERATE_OK])
    api.generate(
        model="m", prompt="p", system="you are a filter", options={"num_predict": 4}
    )

    sent = transport.seen[0]
    assert sent["url"] == "http://ollama.test/api/generate"
    assert sent["body"]["system"] == "you are a filter"
    assert sent["body"]["options"] == {"num_predict": 4}
    # Batch job, nobody watching: streaming would only complicate the seam.
    assert sent["body"]["stream"] is False


def test_truncated_completion_is_flagged() -> None:
    api, _ = client([GENERATE_OK | {"done_reason": "length"}])
    assert api.generate(model="m", prompt="p").truncated is True


def test_missing_response_field_is_an_error() -> None:
    api, _ = client([{"model": "m", "done": True}])
    with pytest.raises(OllamaError, match="no 'response' field"):
        api.generate(model="m", prompt="p")


def test_ollama_error_field_is_surfaced() -> None:
    api, _ = client([{"error": "model 'nope' not found"}])
    with pytest.raises(OllamaError, match="not found"):
        api.generate(model="nope", prompt="p")


def test_non_json_answer_is_an_error() -> None:
    def transport(url: str, body: bytes, timeout: float) -> bytes:
        return b"<html>proxy error</html>"

    api = OllamaClient(host="http://ollama.test", transport=transport)
    with pytest.raises(OllamaError, match="did not answer with JSON"):
        api.generate(model="m", prompt="p")


def test_transport_failure_propagates_as_ollama_error() -> None:
    def transport(url: str, body: bytes, timeout: float) -> bytes:
        raise OllamaError("cannot reach Ollama at http://ollama.test. Is `ollama serve` running?")

    api = OllamaClient(host="http://ollama.test", transport=transport)
    with pytest.raises(OllamaError, match="ollama serve"):
        api.generate(model="m", prompt="p")


def test_embed_returns_the_first_vector() -> None:
    api, transport = client([{"embeddings": [[0.5, -0.25]]}])
    assert api.embed(model="nomic-embed-text", text="hello") == [0.5, -0.25]
    assert json.loads(json.dumps(transport.seen[0]["body"]))["input"] == "hello"


def test_embed_rejects_an_empty_answer() -> None:
    api, _ = client([{"embeddings": []}])
    with pytest.raises(OllamaError, match="embeddings"):
        api.embed(model="nomic-embed-text", text="hello")


def test_host_trailing_slash_does_not_double_up() -> None:
    api, transport = client([GENERATE_OK])
    api.host = "http://ollama.test/"
    api.generate(model="m", prompt="p")
    assert transport.seen[0]["url"] == "http://ollama.test/api/generate"


def test_deadline_caps_the_call_timeout_and_then_refuses_new_calls() -> None:
    transport = scripted_transport([GENERATE_OK])
    now = [1000.0]
    api = OllamaClient(
        host="http://ollama.test",
        transport=transport,
        timeout_s=1800.0,
        deadline=1060.0,
        clock=lambda: now[0],
    )

    api.generate(model="qwen2.5:1.5b", prompt="rate this")
    # The per-call timeout never outlives the run budget.
    assert transport.seen[0]["timeout"] == pytest.approx(60.0)

    now[0] = 1060.0
    with pytest.raises(OllamaError, match="budget"):
        api.generate(model="qwen2.5:1.5b", prompt="rate this")
    assert len(transport.seen) == 1  # refused before touching the network
