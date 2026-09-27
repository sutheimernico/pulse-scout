"""The web API: finished digests, read-only, for the phone.

This process computes nothing. Every number the screen shows was fixed when the digest was
built and stored whole (`core/digest.py`); the API hands that record over as it is. A figure
derived here would be a figure nobody can check against the run that produced it.

Access is fail-closed (plan D-P13):

* **No token configured** → the server binds to loopback only (`bind_host`) and the API is
  open, because only this machine can reach it.
* **Token configured** → the server may bind to all interfaces, and every `/api/*` request
  without the token gets a 401. There is deliberately no loopback exception: `tailscale serve`
  forwards the phone's requests from 127.0.0.1, so "local" says nothing about who is asking.

The phone sends the token once as `?token=…`; the answer sets it as an httpOnly cookie so the
installed app never has to carry it in a URL again. A header works too, for scripts.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pulse_scout.store import repo
from pulse_scout.store.db import DEFAULT_DB_PATH, connect

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIST = ROOT / "frontend" / "dist"
DEFAULT_HEALTH_FILE = ROOT / "data" / "source_health.json"

TOKEN_COOKIE = "pulse_token"
TOKEN_HEADER = "x-pulse-token"
COOKIE_MAX_AGE = 180 * 24 * 3600

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bind_host(token: str | None) -> str:
    """Where the server may listen. Without a token, nothing but this machine gets in."""
    return "0.0.0.0" if token else "127.0.0.1"


def _supplied_token(request: Request) -> str:
    return (
        request.query_params.get("token")
        or request.headers.get(TOKEN_HEADER)
        or request.cookies.get(TOKEN_COOKIE)
        or ""
    )


def _payload(row: Any) -> dict[str, Any]:
    return json.loads(row["payload"])


def create_app(
    *,
    db_path: Path | None = None,
    token: str | None = None,
    dist: Path | None = DEFAULT_DIST,
    health_file: Path = DEFAULT_HEALTH_FILE,
) -> FastAPI:
    app = FastAPI(title="pulse-scout", docs_url=None, redoc_url=None, openapi_url=None)
    database = db_path or DEFAULT_DB_PATH

    if token:

        @app.middleware("http")
        async def token_gate(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            supplied = _supplied_token(request)
            # Bytes, not str: compare_digest raises on non-ASCII str, and a junk ?token=ü
            # must be a 401, not a 500.
            valid = bool(supplied) and hmac.compare_digest(supplied.encode(), token.encode())
            if request.url.path.startswith("/api/") and not valid:
                return JSONResponse({"detail": "Nicht autorisiert."}, status_code=401)
            response = await call_next(request)
            if valid and request.query_params.get("token"):
                response.set_cookie(
                    TOKEN_COOKIE,
                    token,
                    max_age=COOKIE_MAX_AGE,
                    httponly=True,
                    samesite="lax",
                )
            return response

    def read(query: Callable[..., Any], *args: Any) -> Any:
        connection = connect(database)
        try:
            return query(connection, *args)
        finally:
            connection.close()

    @app.get("/api/digest/latest")
    def latest() -> dict[str, Any]:
        row = read(repo.latest_digest)
        if row is None:
            raise HTTPException(status_code=404, detail="Noch kein Digest gebaut.")
        return _payload(row)

    @app.get("/api/digest/{digest_date}")
    def by_date(digest_date: str) -> dict[str, Any]:
        row = read(repo.digest_for, digest_date) if _DATE.match(digest_date) else None
        if row is None:
            raise HTTPException(status_code=404, detail=f"Kein Digest für {digest_date}.")
        return _payload(row)

    @app.get("/api/digests")
    def dates() -> dict[str, list[str]]:
        return {"dates": read(repo.digest_dates)}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        run = read(repo.latest_run)
        digest = read(repo.latest_digest)
        sources: dict[str, Any] | None = None
        if health_file.is_file():
            survey = json.loads(health_file.read_text(encoding="utf-8"))
            sources = {
                key: survey.get(key)
                for key in ("checked_at", "sources_total", "failed", "skipped_fragile")
            }
        return {
            "last_run": dict(run) if run is not None else None,
            "latest_digest": (
                {"date": digest["digest_date"], "generated_at": digest["generated_at"]}
                if digest is not None
                else None
            ),
            "source_survey": sources,
        }

    if dist is not None and (dist / "index.html").is_file():
        # html=True serves index.html for "/" — the whole app is one page.
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
