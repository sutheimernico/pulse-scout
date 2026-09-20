"""Tests for the raw cache.

The important one is `test_the_cache_refuses_to_escape_its_root`: raw feed text must never be
written where a commit could pick it up, and a gitignore entry alone is not a guarantee.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse_scout.sources.cache import DEFAULT_CACHE_ROOT, CacheError, RawCache, slugify


def test_slugify_makes_a_safe_stem() -> None:
    assert slugify("HuggingFace Trending") == "huggingface-trending"
    assert slugify("Anthropic (X mirror, main)") == "anthropic-x-mirror-main"
    assert slugify("The Block (crypto)") == "the-block-crypto"


def test_slugify_rejects_a_name_with_nothing_usable() -> None:
    with pytest.raises(CacheError, match="no usable characters"):
        slugify("///")


def test_store_and_load_round_trip(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    when = date(2026, 9, 20)
    path = cache.store("FastAPI releases", b"<feed/>", kind="atom", when=when)

    assert path == tmp_path / "2026-09-20" / "fastapi-releases.xml"
    assert cache.load("FastAPI releases", kind="atom", when=when) == b"<feed/>"


def test_json_sources_get_a_json_extension(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    path = cache.store("Lobsters", b"[]", kind="json", when=date(2026, 9, 20))
    assert path.suffix == ".json"


def test_loading_something_never_stored_returns_none(tmp_path: Path) -> None:
    assert RawCache(tmp_path).load("Nothing", when=date(2026, 9, 20)) is None


def test_the_cache_refuses_to_escape_its_root(tmp_path: Path) -> None:
    """A source named '../../data/x' must not be able to write into the repository."""
    cache = RawCache(tmp_path / "raw")
    with pytest.raises(CacheError, match="outside the cache root"):
        cache._checked(Path("../../data/sources.toml"))


def test_the_default_root_is_inside_the_gitignored_cache_directory() -> None:
    assert DEFAULT_CACHE_ROOT.parts[-2:] == (".cache", "raw")


def test_prune_removes_only_old_day_directories(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    cache.store("A", b"x", when=date(2026, 9, 1))
    cache.store("B", b"x", when=date(2026, 9, 19))
    (tmp_path / "notes").mkdir()

    removed = cache.prune(max_age_days=14, today=date(2026, 9, 20))

    assert removed == 1
    assert not (tmp_path / "2026-09-01").exists()
    assert (tmp_path / "2026-09-19").exists()
    # Anything we did not write stays — the cache only owns its own day directories.
    assert (tmp_path / "notes").exists()


def test_prune_on_an_empty_cache_is_a_no_op(tmp_path: Path) -> None:
    assert RawCache(tmp_path / "missing").prune() == 0
