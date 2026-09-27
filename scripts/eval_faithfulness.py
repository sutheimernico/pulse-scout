#!/usr/bin/env python3
"""Measure the faithfulness guard against a hand-labelled set of real sentences.

    uv run python scripts/eval_faithfulness.py                      # qwen2.5:7b
    uv run python scripts/eval_faithfulness.py --model qwen2.5:1.5b
    uv run python scripts/eval_faithfulness.py --write              # record the result

The labels live in `data/eval/faithfulness_labels.json` and hold no third-party text: each one
names an item by its key, and the source text is read from the local database — exactly the
view the writer was given. So the set is committed, but it only runs on a machine whose
database has seen those items. Missing items are reported, never silently skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.core.faithfulness import score_labels  # noqa: E402
from pulse_scout.llm.ollama import OllamaClient  # noqa: E402
from pulse_scout.llm.prompts import VERIFY_SYSTEM  # noqa: E402
from pulse_scout.llm.verifier import DEFAULT_VERIFY_MODEL, check_sentence, source_view  # noqa: E402
from pulse_scout.models import Item  # noqa: E402
from pulse_scout.store.db import connect  # noqa: E402

LABELS = ROOT / "data" / "eval" / "faithfulness_labels.json"


def load_item(connection, key: str) -> Item | None:
    row = connection.execute(
        "SELECT item_key, source_name, tier, title, summary FROM items WHERE item_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return Item(
        key=row["item_key"],
        source_name=row["source_name"],
        tier=row["tier"],
        title=row["title"],
        summary=row["summary"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_VERIFY_MODEL)
    parser.add_argument("--write", action="store_true", help="record to data/benchmarks/")
    parser.add_argument("--tag", default="", help="suffix for the recorded file")
    args = parser.parse_args()

    labels = json.loads(LABELS.read_text(encoding="utf-8"))["sentences"]
    connection = connect()
    client = OllamaClient()

    truth: list[bool] = []
    kept: list[bool] = []
    by_kind: dict[str, tuple[list[bool], list[bool]]] = defaultdict(lambda: ([], []))
    misses: list[dict[str, str]] = []
    interpretation_kept: list[bool] = []
    clear_truth: list[bool] = []
    clear_kept: list[bool] = []
    missing = 0
    started = time.monotonic()

    # Grouped by item so consecutive calls share the source prefix, as they do in a real run.
    for entry in sorted(labels, key=lambda e: e["item_key"]):
        item = load_item(connection, entry["item_key"])
        if item is None:
            missing += 1
            continue
        verdict = check_sentence(
            client, source=source_view(item), sentence=entry["sentence"], model=args.model
        )
        if entry["label"] == "interpretation":
            # Makes no claim about the source, so it is neither caught nor a false alarm.
            # What the guard does with it is still worth knowing: it lives in the body.
            interpretation_kept.append(verdict.keep)
            print(".", end="", flush=True)
            continue
        faithful = entry["label"] == "faithful"
        truth.append(faithful)
        kept.append(verdict.keep)
        by_kind[entry["kind"]][0].append(faithful)
        by_kind[entry["kind"]][1].append(verdict.keep)
        if not entry.get("borderline"):
            clear_truth.append(faithful)
            clear_kept.append(verdict.keep)
        if verdict.keep != faithful:
            misses.append(
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "answer": verdict.answer,
                    "sentence": entry["sentence"],
                }
            )
        print(".", end="", flush=True)
    connection.close()
    seconds = time.monotonic() - started
    print()

    result = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": args.model,
        "tag": args.tag,
        "system_prompt": VERIFY_SYSTEM,
        "labels_file": str(LABELS.relative_to(ROOT)),
        "missing_items": missing,
        "seconds": round(seconds, 1),
        "seconds_per_sentence": round(
            seconds / max(1, len(truth) + len(interpretation_kept)), 2
        ),
        "overall": score_labels(truth, kept),
        "clear_cases_only": score_labels(clear_truth, clear_kept),
        "by_kind": {kind: score_labels(t, k) for kind, (t, k) in sorted(by_kind.items())},
        "interpretation": {
            "sentences": len(interpretation_kept),
            "kept": sum(interpretation_kept),
            "dropped": len(interpretation_kept) - sum(interpretation_kept),
        },
        "wrong_calls": misses,
    }
    shown = ("model", "seconds", "overall", "clear_cases_only", "by_kind", "interpretation")
    print(json.dumps({k: result[k] for k in shown}, indent=1))
    for miss in misses:
        print(f"  WRONG {miss['id']} ({miss['label']}, said {miss['answer']!r})")

    if args.write:
        out = ROOT / "data" / "benchmarks"
        out.mkdir(parents=True, exist_ok=True)
        tag = f"-{args.tag}" if args.tag else ""
        name = f"{datetime.now():%Y-%m-%d}-faithfulness-{args.model.replace(':', '-')}{tag}.json"
        (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"wrote data/benchmarks/{name}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
