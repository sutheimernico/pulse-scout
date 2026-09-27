#!/usr/bin/env python3
"""Serve the digest to the phone.

    uv run python scripts/serve.py                  # token from .env or the environment
    uv run python scripts/serve.py --require-token  # what the systemd unit runs

Binding follows the token (plan D-P13): without `PULSE_DASH_TOKEN` the server listens on
127.0.0.1 only; with it, on all interfaces, and every `/api/*` call must carry the token.

`--require-token` refuses to start without one. The unit uses it because `tailscale serve`
forwards the phone to 127.0.0.1 — a loopback bind alone would not keep the tailnet out.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from pulse_scout.api import bind_host, create_app  # noqa: E402
from pulse_scout.config import read_env_file  # noqa: E402

DEFAULT_PORT = 8430


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--require-token", action="store_true")
    args = parser.parse_args()

    settings = {**read_env_file(ROOT / ".env"), **os.environ}
    token = settings.get("PULSE_DASH_TOKEN") or None
    port = args.port or int(settings.get("PULSE_DASH_PORT") or DEFAULT_PORT)

    if args.require_token and not token:
        print("refusing to start: PULSE_DASH_TOKEN is empty (see .env.example)", file=sys.stderr)
        return 2

    host = bind_host(token)
    gate = "token required on /api/*" if token else "no token — loopback only"
    print(f"pulse-scout on http://{host}:{port}  ({gate})", flush=True)
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
