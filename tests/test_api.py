"""Tests for the read-only API and its fail-closed token gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pulse_scout.api import TOKEN_COOKIE, TOKEN_HEADER, bind_host, create_app
from pulse_scout.config import read_env_file
from pulse_scout.store import repo
from pulse_scout.store.db import connect

TOKEN = "correct-horse-battery-staple"


def payload(day: str, *, seen: int = 412) -> str:
    return json.dumps(
        {
            "digest_date": day,
            "generated_at": f"{day}T21:30:00+02:00",
            "cards": [],
            "thread": "",
            "kuer": [],
            "counters": {"items_seen": seen},
            "read_seconds": 42,
            "notes": [],
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "pulse.db"
    connection = connect(path)
    for day, seen in (("2026-09-26", 300), ("2026-09-27", 412)):
        repo.save_digest(
            connection,
            digest_date=day,
            generated_at=f"{day}T21:30:00+02:00",
            payload=payload(day, seen=seen),
            read_seconds=42,
            card_count=0,
        )
    run = repo.start_run(connection, now=datetime(2026, 9, 27, 19, 0, tzinfo=UTC))
    repo.finish_run(
        connection,
        run,
        now=datetime(2026, 9, 27, 19, 8, tzinfo=UTC),
        counters={"items_seen": 412, "candidates": 40},
    )
    connection.close()
    return path


def client_for(db: Path, tmp_path: Path, token: str | None = None) -> TestClient:
    return TestClient(
        create_app(db_path=db, token=token, dist=None, health_file=tmp_path / "none.json")
    )


# --- binding ------------------------------------------------------------------------------


def test_without_a_token_only_this_machine_can_connect() -> None:
    assert bind_host(None) == "127.0.0.1"
    assert bind_host("") == "127.0.0.1"


def test_with_a_token_the_phone_may_connect() -> None:
    assert bind_host(TOKEN) == "0.0.0.0"


# --- reading --------------------------------------------------------------------------------


def test_without_a_token_the_api_is_open(db: Path, tmp_path: Path) -> None:
    response = client_for(db, tmp_path).get("/api/digest/latest")
    assert response.status_code == 200
    assert response.json()["digest_date"] == "2026-09-27"


def test_the_latest_digest_carries_the_stored_funnel_numbers(db: Path, tmp_path: Path) -> None:
    body = client_for(db, tmp_path).get("/api/digest/latest").json()
    assert body["counters"]["items_seen"] == 412


def test_a_digest_is_found_by_its_date(db: Path, tmp_path: Path) -> None:
    body = client_for(db, tmp_path).get("/api/digest/2026-09-26").json()
    assert body["counters"]["items_seen"] == 300


@pytest.mark.parametrize("day", ["2026-09-19", "gestern", "2026-9-1"])
def test_an_unknown_date_is_404_never_an_empty_shell(db: Path, tmp_path: Path, day: str) -> None:
    response = client_for(db, tmp_path).get(f"/api/digest/{day}")
    assert response.status_code == 404
    assert "digest_date" not in response.json()


def test_no_digest_at_all_is_404(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    connect(empty).close()
    response = client_for(empty, tmp_path).get("/api/digest/latest")
    assert response.status_code == 404


def test_the_date_list_is_newest_first(db: Path, tmp_path: Path) -> None:
    body = client_for(db, tmp_path).get("/api/digests").json()
    assert body == {"dates": ["2026-09-27", "2026-09-26"]}


def test_health_reports_the_last_run_and_digest(db: Path, tmp_path: Path) -> None:
    survey = tmp_path / "health.json"
    survey.write_text(json.dumps({"checked_at": "x", "sources_total": 60, "failed": 0}))
    app = create_app(db_path=db, dist=None, health_file=survey)
    body = TestClient(app).get("/api/health").json()
    assert body["last_run"]["items_seen"] == 412
    assert body["latest_digest"]["date"] == "2026-09-27"
    assert body["source_survey"]["sources_total"] == 60


# --- the token gate -------------------------------------------------------------------------


def test_with_a_token_configured_a_request_without_it_is_refused(
    db: Path, tmp_path: Path
) -> None:
    client = client_for(db, tmp_path, token=TOKEN)
    for path in ("/api/digest/latest", "/api/digests", "/api/health", "/api/digest/2026-09-27"):
        assert client.get(path).status_code == 401, path


def test_a_wrong_token_is_refused(db: Path, tmp_path: Path) -> None:
    client = client_for(db, tmp_path, token=TOKEN)
    assert client.get("/api/digest/latest", headers={TOKEN_HEADER: "wrong"}).status_code == 401


def test_the_token_works_as_header_query_or_cookie(db: Path, tmp_path: Path) -> None:
    client = client_for(db, tmp_path, token=TOKEN)
    assert client.get("/api/digest/latest", headers={TOKEN_HEADER: TOKEN}).status_code == 200
    assert client.get(f"/api/digest/latest?token={TOKEN}").status_code == 200
    client.cookies.set(TOKEN_COOKIE, TOKEN)
    assert client.get("/api/digest/latest").status_code == 200


def test_the_token_in_the_url_becomes_a_cookie(db: Path, tmp_path: Path) -> None:
    client = client_for(db, tmp_path, token=TOKEN)
    response = client.get(f"/api/digests?token={TOKEN}")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{TOKEN_COOKIE}=")
    assert "HttpOnly" in cookie
    # The follow-up request carries the cookie on its own.
    assert client.get("/api/digest/latest").status_code == 200


def test_a_loopback_request_is_not_exempt(db: Path, tmp_path: Path) -> None:
    """tailscale serve forwards the phone from 127.0.0.1 — local says nothing about who asks."""
    app = create_app(db_path=db, token=TOKEN, dist=None, health_file=tmp_path / "x.json")
    client = TestClient(app, client=("127.0.0.1", 50000))
    assert client.get("/api/digest/latest").status_code == 401


# --- the frontend ---------------------------------------------------------------------------


def test_the_built_frontend_is_served_without_a_token(db: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>pulse</title>")
    app = create_app(db_path=db, token=TOKEN, dist=dist, health_file=tmp_path / "x.json")
    client = TestClient(app)
    assert "pulse" in client.get("/").text
    assert client.get("/api/digest/latest").status_code == 401


def test_without_a_build_there_is_no_frontend(db: Path, tmp_path: Path) -> None:
    assert client_for(db, tmp_path).get("/").status_code == 404


# --- .env ---------------------------------------------------------------------------------


def test_the_env_file_is_read_without_a_dependency(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nPULSE_DASH_TOKEN=abc\nPULSE_DASH_PORT = 8430\nQUOTED='x y'\n\n")
    assert read_env_file(env) == {"PULSE_DASH_TOKEN": "abc", "PULSE_DASH_PORT": "8430",
                                  "QUOTED": "x y"}
    assert read_env_file(tmp_path / "missing") == {}
