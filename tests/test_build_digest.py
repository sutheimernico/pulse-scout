"""A failed digest run must not use up the items it fetched."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from pulse_scout.llm.writer import WriterError
from pulse_scout.store import repo
from pulse_scout.store.db import connect
from tests.test_store import item

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_digest.py"


def load_script():
    spec = importlib.util.spec_from_file_location("build_digest_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_run_that_fails_after_the_funnel_gives_its_items_back(tmp_path, monkeypatch) -> None:
    module = load_script()
    db_path = tmp_path / "pulse.db"

    def fake_funnel(*, connection, now, **_):
        repo.record_seen(connection, [item("Fresh story")], now=now)
        return SimpleNamespace(
            candidates=[object()],
            counters=SimpleNamespace(headline=lambda: "1 gesichtet"),
            run_id=1,
        )

    def writer_down(*_, **__):
        raise WriterError("model busy")

    monkeypatch.setattr(module, "load_sources", lambda: [])
    monkeypatch.setattr(module, "load_profile", lambda: None)
    monkeypatch.setattr(module, "UrllibFetcher", lambda: None)
    monkeypatch.setattr(module, "RawCache", lambda: None)
    monkeypatch.setattr(module, "run_funnel", fake_funnel)
    monkeypatch.setattr(
        module,
        "score_candidates",
        lambda *_, **__: SimpleNamespace(
            scored=[],
            parse_failures=0,
            call_failures=0,
            rank_correlation=None,
            seconds=0.0,
            finalists=lambda _n: [],
        ),
    )
    monkeypatch.setattr(module, "select", lambda *_: None)
    monkeypatch.setattr(module, "write_digest", writer_down)
    monkeypatch.setattr(sys, "argv", ["build_digest.py", "--db", str(db_path)])

    assert module.main() == 3

    connection = connect(db_path)
    assert repo.count_items(connection) == 0
    connection.close()
