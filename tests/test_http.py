"""Tests for the network seam. No test here opens a socket."""

from __future__ import annotations

import gzip

import pytest

from pulse_scout.sources.http import DEFAULT_USER_AGENT, FetchResult, UrllibFetcher


class RecordingTransport:
    """A transport that answers from a script and remembers what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if not self.responses:
            raise AssertionError("transport ran out of scripted responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def fetcher(*responses, **kwargs) -> tuple[UrllibFetcher, RecordingTransport]:
    transport = RecordingTransport(*responses)
    return (
        UrllibFetcher(
            transport=transport,
            sleep=lambda _seconds: None,
            clock=FakeClock(),
            **kwargs,
        ),
        transport,
    )


def test_a_successful_fetch_returns_the_body() -> None:
    api, transport = fetcher((200, {"etag": 'W/"abc"'}, b"<rss/>"))
    result = api.fetch("https://example.com/feed.xml")

    assert result.ok is True
    assert result.body == b"<rss/>"
    assert result.etag == 'W/"abc"'
    assert transport.calls[0]["headers"]["User-Agent"] == DEFAULT_USER_AGENT


def test_the_configured_user_agent_is_sent() -> None:
    api, transport = fetcher((200, {}, b"x"), user_agent="pulse-scout/test")
    api.fetch("https://example.com/f")
    assert transport.calls[0]["headers"]["User-Agent"] == "pulse-scout/test"


def test_conditional_headers_are_sent_when_we_have_them() -> None:
    api, transport = fetcher((304, {}, b""))
    result = api.fetch("https://example.com/f", etag='"v1"', last_modified="Sat, 20 Sep 2026")

    sent = transport.calls[0]["headers"]
    assert sent["If-None-Match"] == '"v1"'
    assert sent["If-Modified-Since"] == "Sat, 20 Sep 2026"
    assert result.unchanged is True
    assert result.ok is False
    # 304 is a correct answer, not a failure — the collector must not log it as one.
    assert result.error == ""


def test_a_404_is_an_error_but_not_an_exception() -> None:
    api, _ = fetcher((404, {}, b"not found"))
    result = api.fetch("https://example.com/gone")
    assert result.ok is False
    assert result.error == "HTTP 404"


def test_a_transport_failure_is_retried_then_returned() -> None:
    api, transport = fetcher(TimeoutError("timed out"), (200, {}, b"ok"))
    result = api.fetch("https://example.com/f")
    assert result.ok is True
    assert len(transport.calls) == 2


def test_a_permanently_dead_host_never_raises() -> None:
    api, transport = fetcher(
        ConnectionRefusedError("refused"), ConnectionRefusedError("refused")
    )
    result = api.fetch("https://nitter.net/AnthropicAI/rss")

    assert isinstance(result, FetchResult)
    assert result.ok is False
    assert "ConnectionRefusedError" in result.error
    assert len(transport.calls) == 2


def test_gzip_bodies_are_decompressed() -> None:
    api, _ = fetcher((200, {"content-encoding": "gzip"}, gzip.compress(b"<feed/>")))
    assert api.fetch("https://example.com/f").body == b"<feed/>"


def test_a_corrupt_gzip_body_is_an_error_not_a_crash() -> None:
    api, _ = fetcher((200, {"content-encoding": "gzip"}, b"not actually gzip"))
    result = api.fetch("https://example.com/f")
    assert result.ok is False
    assert "undecodable" in result.error


def test_the_same_host_is_not_hammered() -> None:
    """All the GitHub release atoms share one host; hitting it in a tight loop gets us blocked."""
    slept: list[float] = []
    clock = FakeClock()
    api = UrllibFetcher(
        transport=RecordingTransport((200, {}, b"a"), (200, {}, b"b")),
        sleep=slept.append,
        clock=clock,
        host_interval_s=1.0,
    )
    api.fetch("https://github.com/fastapi/fastapi/releases.atom")
    clock.advance(0.3)
    api.fetch("https://github.com/pydantic/pydantic/releases.atom")

    assert slept, "the second request to the same host must wait"
    assert slept[0] == pytest.approx(0.7)


def test_different_hosts_do_not_wait_for_each_other() -> None:
    slept: list[float] = []
    api = UrllibFetcher(
        transport=RecordingTransport((200, {}, b"a"), (200, {}, b"b")),
        sleep=slept.append,
        clock=FakeClock(),
        host_interval_s=1.0,
    )
    api.fetch("https://github.com/a/b/releases.atom")
    api.fetch("https://lobste.rs/hottest.json")
    assert slept == []
