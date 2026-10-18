"""The model seam.

Every call to Ollama in this project goes through `Client`. Tests inject a fake instead of a
transport, so no test ever needs a running model or a network.

Two things are deliberate here:

* **Timings come back with every completion.** Throughput is the binding constraint of the
  whole design (18,1 tokens/s intake, 4,5 tokens/s generation on this CPU), so a call that
  does not report what it cost is not useful. Ollama reports durations in nanoseconds; they
  are converted once, at the edge.
* **No streaming.** The pipeline is a batch job with nobody watching. Streaming would buy
  nothing and complicate the seam.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_HOST = "http://localhost:11434"

# A 7B model writing ~700 tokens on a CPU takes minutes, not seconds. A short timeout here
# would look exactly like a broken model.
DEFAULT_TIMEOUT_S = 1800.0

_NS_PER_S = 1_000_000_000


class OllamaError(RuntimeError):
    """Ollama could not be reached, or answered with something unusable."""


@dataclass(frozen=True, slots=True)
class Completion:
    """One generation, with what it cost."""

    text: str
    model: str
    prompt_tokens: int
    output_tokens: int
    prompt_seconds: float
    output_seconds: float
    total_seconds: float
    load_seconds: float
    done_reason: str = ""

    @property
    def prompt_tokens_per_second(self) -> float:
        return self.prompt_tokens / self.prompt_seconds if self.prompt_seconds > 0 else 0.0

    @property
    def output_tokens_per_second(self) -> float:
        return self.output_tokens / self.output_seconds if self.output_seconds > 0 else 0.0

    @property
    def truncated(self) -> bool:
        """The model hit the output cap instead of finishing its sentence."""
        return self.done_reason == "length"


class Client(Protocol):
    """What the rest of the codebase is allowed to know about the model."""

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Completion: ...

    def embed(self, *, model: str, text: str) -> list[float]: ...


Transport = Callable[[str, bytes, float], bytes]
"""url, json payload, timeout -> raw response body. Injected so tests stay offline."""


def _urllib_transport(url: str, payload: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise OllamaError(f"{url} answered HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"cannot reach Ollama at {url} ({exc.reason}). Is `ollama serve` running?"
        ) from exc
    except TimeoutError as exc:
        raise OllamaError(f"{url} timed out after {timeout:.0f}s") from exc


def _seconds(raw: dict[str, Any], key: str) -> float:
    value = raw.get(key)
    return value / _NS_PER_S if isinstance(value, int | float) else 0.0


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    return int(value) if isinstance(value, int | float) else 0


@dataclass(slots=True)
class OllamaClient:
    """The real client. One instance per run is enough; it holds no state."""

    host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    timeout_s: float = DEFAULT_TIMEOUT_S
    transport: Transport = _urllib_transport
    # Wall-clock epoch after which no call starts. Without it a busy Ollama (another project
    # holding the model) turns 40 scoring calls into 40 x timeout_s of waiting: on 2026-10-16
    # one run hung for 40 hours and the digest slot was lost. Wall clock, not monotonic: the
    # monotonic clock stands still while the host sleeps, which is when runs went missing.
    deadline: float | None = None
    clock: Callable[[], float] = time.time

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.host.rstrip('/')}{path}"
        timeout = self.timeout_s
        if self.deadline is not None:
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise OllamaError("run time budget used up before this call (model busy or stuck)")
            timeout = min(timeout, remaining)
        raw = self.transport(url, json.dumps(body).encode("utf-8"), timeout)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"{url} did not answer with JSON: {raw[:200]!r}") from exc
        if not isinstance(parsed, dict):
            raise OllamaError(f"{url} answered with {type(parsed).__name__}, expected an object")
        if "error" in parsed:
            raise OllamaError(f"{url} reported: {parsed['error']}")
        return parsed

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Completion:
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system is not None:
            body["system"] = system
        if options:
            body["options"] = options

        raw = self._post("/api/generate", body)
        text = raw.get("response")
        if not isinstance(text, str):
            raise OllamaError(f"{model} returned no 'response' field: {sorted(raw)}")

        return Completion(
            text=text,
            model=str(raw.get("model", model)),
            prompt_tokens=_int(raw, "prompt_eval_count"),
            output_tokens=_int(raw, "eval_count"),
            prompt_seconds=_seconds(raw, "prompt_eval_duration"),
            output_seconds=_seconds(raw, "eval_duration"),
            total_seconds=_seconds(raw, "total_duration"),
            load_seconds=_seconds(raw, "load_duration"),
            done_reason=str(raw.get("done_reason", "")),
        )

    def embed(self, *, model: str, text: str) -> list[float]:
        raw = self._post("/api/embed", {"model": model, "input": text})
        vectors = raw.get("embeddings")
        if not isinstance(vectors, list) or not vectors or not isinstance(vectors[0], list):
            raise OllamaError(f"{model} returned no usable 'embeddings': {sorted(raw)}")
        return [float(value) for value in vectors[0]]
