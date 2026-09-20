"""The network seam.

Every outbound request in this project goes through `Fetcher`. Tests inject a transport, so
the suite never needs connectivity — that is a hard rule, not a preference.

Three behaviours here are not incidental:

* **A failure is a return value, not an exception.** 63 sources are fetched once a day and
  some of them will be down. The collector needs to record that and carry on; a raised
  exception would either kill the run or get swallowed somewhere less careful.
* **Conditional GET.** Most of the configured sources are snapshots that barely change — the
  Azure feed returns the same 200 entries for hours. Sending the stored ETag turns most of a
  daily run into 304s, which is both faster and the polite thing to do.
* **A per-host minimum interval.** Several sources share a host (all the GitHub release
  atoms, both HuggingFace endpoints). Hammering them in a tight loop is exactly the behaviour
  that gets a key-less client blocked, and being blocked is how this project dies.
"""

from __future__ import annotations

import gzip
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_USER_AGENT = "pulse-scout/0.1 (personal daily digest; contact via github)"

# One request per host per second. Well inside every documented limit (Hacker News allows
# 10.000/hour) and slow enough that no operator would call it abuse.
DEFAULT_HOST_INTERVAL_S = 1.0


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What came back, including the bad news."""

    url: str
    status: int = 0
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    elapsed_s: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    @property
    def unchanged(self) -> bool:
        """The server says our cached copy is still current."""
        return self.status == 304

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")


class Fetcher(Protocol):
    def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult: ...


Transport = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes]]
"""url, headers, timeout -> (status, headers, body). Raises on transport failure."""


def _decode_body(body: bytes, headers: Mapping[str, str]) -> bytes:
    encoding = headers.get("content-encoding", "").lower()
    if "gzip" in encoding:
        return gzip.decompress(body)
    if "deflate" in encoding:
        return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def urllib_transport(
    url: str, headers: dict[str, str], timeout: float
) -> tuple[int, dict[str, str], bytes]:
    """The real transport. Kept separate so the fetcher's logic is testable without it."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            got = {k.lower(): v for k, v in response.headers.items()}
            return response.status, got, response.read()
    except urllib.error.HTTPError as exc:
        # 304 and 404 are answers, not transport failures — hand them back like any other.
        got = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        return exc.code, got, exc.read() if exc.code not in (204, 304) else b""


@dataclass(slots=True)
class UrllibFetcher:
    """The real fetcher. One instance per run; it holds the per-host clock."""

    user_agent: str = field(
        default_factory=lambda: os.environ.get("PULSE_USER_AGENT", DEFAULT_USER_AGENT)
    )
    timeout_s: float = DEFAULT_TIMEOUT_S
    host_interval_s: float = DEFAULT_HOST_INTERVAL_S
    retries: int = 1
    transport: Transport = urllib_transport
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _last_hit: dict[str, float] = field(default_factory=dict, init=False)

    def _wait_for_host(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).hostname or ""
        previous = self._last_hit.get(host)
        now = self.clock()
        if previous is not None:
            remaining = self.host_interval_s - (now - previous)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_hit[host] = now

    def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            # Several verified feeds answer with text/html and still return valid XML, so the
            # Accept header is a hint at best. The body gets sniffed either way.
            "Accept": "application/atom+xml, application/rss+xml, application/xml, "
            "application/json;q=0.9, */*;q=0.8",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        last_error = ""
        for _attempt in range(self.retries + 1):
            self._wait_for_host(url)
            started = self.clock()
            try:
                status, got, raw = self.transport(url, dict(headers), self.timeout_s)
            except Exception as exc:  # noqa: BLE001 — a dead source must never kill the run
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            elapsed = self.clock() - started
            try:
                body = _decode_body(raw, got)
            except (OSError, zlib.error) as exc:
                return FetchResult(
                    url=url,
                    status=status,
                    headers=got,
                    elapsed_s=elapsed,
                    error=f"undecodable body: {exc}",
                )
            error = "" if status in (200, 304) else f"HTTP {status}"
            return FetchResult(
                url=url, status=status, body=body, headers=got, elapsed_s=elapsed, error=error
            )

        return FetchResult(url=url, error=last_error or "unreachable")
