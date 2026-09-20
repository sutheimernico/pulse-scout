"""The writing pass: the 7B model turns twelve finalists into five judgements and a thread.

This is the only step where the model produces text a human reads, and it is the slowest thing
in the daily run — measured on this machine, roughly 4 000 tokens in and 700 out is minutes of
full CPU load. Everything here is therefore built around two constraints: keep the prompt
small, and never ship what comes back without checking it.

The model is given short opaque ids (`a1`, `a2`, …) rather than URLs. That is not decoration:
it costs fewer tokens, and it turns "did the model make this up?" into an exact lookup instead
of a fuzzy comparison.

One retry, then the run fails. A second failure means the model cannot produce a usable digest
today, and the specified behaviour for that is a visible failure — yesterday's digest stays the
latest one rather than being replaced by something plausible.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pulse_scout.core.validate import DigestRejected, validate_judgements
from pulse_scout.llm.ollama import Client, OllamaError
from pulse_scout.llm.prompts import WRITE_SYSTEM, write_prompt
from pulse_scout.llm.scorer import ScoredCandidate
from pulse_scout.models import Item, Judgement

DEFAULT_WRITE_MODEL = "qwen2.5:7b"

# 700 output tokens is the spec's budget for five judgements plus the thread.
DEFAULT_OUTPUT_CAP = 700

# How much of each item's summary the model sees. Twelve items at ~300 characters is roughly
# 1 000 tokens of context; the rest of the budget is the system block and the output.
SUMMARY_BUDGET = 300

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class WriterError(RuntimeError):
    """The model could not be reached, or answered with something that is not JSON."""


@dataclass(frozen=True, slots=True)
class Draft:
    """A validated digest body, ready to be stored."""

    judgements: list[Judgement] = field(default_factory=list)
    thread: str = ""
    items: dict[str, Item] = field(default_factory=dict)
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    attempts: int = 1
    truncated: bool = False


def short_ids(finalists: Sequence[ScoredCandidate]) -> dict[str, Item]:
    """`a1` … `aN` in finalist order, mapped to the item each one stands for."""
    return {
        f"a{index}": entry.candidate.cluster.primary
        for index, entry in enumerate(finalists, start=1)
    }


def render_items(items: dict[str, Item]) -> str:
    lines = []
    for handle, item in items.items():
        summary = item.summary[:SUMMARY_BUDGET].strip()
        lines.append(f"[{handle}] {item.title} ({item.source_name})")
        if summary:
            lines.append(f"      {summary}")
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Pull the JSON object out of whatever the model wrapped it in."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise WriterError(f"no JSON object in the answer: {cleaned[:200]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise WriterError(f"the answer is not valid JSON ({exc}): {cleaned[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise WriterError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def parse_draft(payload: dict) -> tuple[list[Judgement], str]:
    raw = payload.get("judgements")
    if not isinstance(raw, list):
        raise WriterError("the answer has no 'judgements' list")
    judgements = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise WriterError(f"a judgement is a {type(entry).__name__}, not an object")
        judgements.append(
            Judgement(
                item_id=str(entry.get("item_id", "")).strip(),
                headline=str(entry.get("headline", "")).strip(),
                body=str(entry.get("body", "")).strip(),
                why_you=str(entry.get("why_you", "")).strip(),
            )
        )
    thread = str(payload.get("thread", "")).strip()
    return judgements, thread


def write_digest(
    finalists: Sequence[ScoredCandidate],
    *,
    client: Client,
    now: datetime,
    model: str = DEFAULT_WRITE_MODEL,
    output_cap: int = DEFAULT_OUTPUT_CAP,
    wanted: int = 5,
    max_attempts: int = 2,
) -> Draft:
    """Ask the 7B model for the digest body and refuse anything that does not check out."""
    if not finalists:
        raise WriterError("nothing to write about — the funnel produced no finalists")

    items = short_ids(finalists)
    prompt = write_prompt(render_items(items), count=min(wanted, len(items)))
    options = {
        "num_predict": output_cap,
        "temperature": 0.2,
        "num_ctx": 8192,
    }

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            completion = client.generate(
                model=model, prompt=prompt, system=WRITE_SYSTEM, options=options
            )
        except OllamaError as exc:
            raise WriterError(str(exc)) from exc

        try:
            judgements, thread = parse_draft(extract_json(completion.text))
            validate_judgements(judgements, thread, items=items, now=now)
        except (WriterError, DigestRejected) as exc:
            last_error = exc
            continue

        return Draft(
            judgements=judgements,
            thread=thread,
            items=items,
            prompt_tokens=completion.prompt_tokens,
            output_tokens=completion.output_tokens,
            seconds=completion.total_seconds,
            attempts=attempt,
            truncated=completion.truncated,
        )

    raise DigestRejected(
        f"the model failed {max_attempts} times; no digest written. Last reason: {last_error}"
    )
