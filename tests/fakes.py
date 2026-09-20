"""Fakes for the two seams: the network and the model.

They live here rather than in `src/` because they are test scaffolding, and because a fake in
the shipped package is a fake somebody eventually runs in production by accident.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pulse_scout.llm.ollama import Completion, OllamaError


@dataclass
class FakeClient:
    """A scripted Ollama. Hands out `replies` in order, records what it was asked."""

    replies: list[str] = field(default_factory=list)
    embedding: Sequence[float] = (0.0, 1.0)
    fail_with: OllamaError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    output_tokens: int = 50
    done_reason: str = "stop"

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Completion:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(
            {"model": model, "prompt": prompt, "system": system, "options": options}
        )
        if not self.replies:
            raise AssertionError("FakeClient ran out of scripted replies")
        text = self.replies.pop(0)
        return Completion(
            text=text,
            model=model,
            prompt_tokens=max(1, len(prompt) // 4),
            output_tokens=self.output_tokens,
            prompt_seconds=0.1,
            output_seconds=0.1,
            total_seconds=0.2,
            load_seconds=0.0,
            done_reason=self.done_reason,
        )

    def embed(self, *, model: str, text: str) -> list[float]:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append({"model": model, "embed": text})
        return list(self.embedding)


def scripted_transport(payloads: Iterable[dict[str, Any]]):
    """A transport that answers each POST with the next dict, JSON-encoded."""
    queue = list(payloads)
    seen: list[dict[str, Any]] = []

    def transport(url: str, body: bytes, timeout: float) -> bytes:
        seen.append({"url": url, "body": json.loads(body), "timeout": timeout})
        if not queue:
            raise AssertionError("scripted_transport ran out of responses")
        return json.dumps(queue.pop(0)).encode("utf-8")

    transport.seen = seen  # type: ignore[attr-defined]
    return transport
