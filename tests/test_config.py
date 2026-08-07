"""Tests for the source list loader.

These also act as a guard on the real config: if someone hand-edits data/sources.toml and
breaks it, the gate catches it before a pipeline run does.
"""

from __future__ import annotations

import pytest

from pulse_scout.config import ConfigError, Source, load_sources, parse_source

MINIMAL = {
    "name": "Example",
    "tier": 1,
    "weight": 1.0,
    "url": "https://example.com/feed.xml",
    "kind": "rss",
    "abstract": True,
}


def test_parses_a_minimal_source() -> None:
    source = parse_source(dict(MINIMAL), 0)
    assert source.name == "Example"
    assert source.tier == 1
    assert source.fragile is False
    assert source.tolerates_failure is False


def test_fragile_source_tolerates_failure() -> None:
    source = parse_source(MINIMAL | {"fragile": True}, 0)
    assert source.tolerates_failure is True


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"tier": 9}, "tier"),
        # bool is a subclass of int, so `True in {1, 2, 3}` passes without an explicit guard.
        ({"tier": True}, "tier"),
        ({"weight": 0}, "weight"),
        ({"weight": -1.0}, "weight"),
        ({"url": "ftp://example.com/x"}, "url"),
        ({"kind": "csv"}, "kind"),
        ({"abstract": "yes"}, "abstract"),
        ({"fragile": "maybe"}, "fragile"),
        ({"name": "  "}, "name"),
    ],
)
def test_rejects_malformed_values(override: dict[str, object], expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        parse_source(MINIMAL | override, 0)


def test_rejects_missing_key() -> None:
    incomplete = {k: v for k, v in MINIMAL.items() if k != "url"}
    with pytest.raises(ConfigError, match="url"):
        parse_source(incomplete, 3)


def test_rejects_boolean_weight() -> None:
    # bool is a subclass of int in Python, so this needs its own guard.
    with pytest.raises(ConfigError, match="weight"):
        parse_source(MINIMAL | {"weight": True}, 0)


def test_rejects_duplicate_urls(tmp_path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[source]]\nname = "A"\ntier = 1\nweight = 1.0\n'
        'url = "https://example.com/f"\nkind = "rss"\nabstract = true\n\n'
        '[[source]]\nname = "B"\ntier = 1\nweight = 1.0\n'
        'url = "https://example.com/f"\nkind = "rss"\nabstract = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate url"):
        load_sources(path)


def test_rejects_empty_file(tmp_path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="no \\[\\[source\\]\\] entries"):
        load_sources(path)


def test_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_sources(tmp_path / "nope.toml")


def test_real_source_list_is_valid() -> None:
    """The shipped config must always load. This is the guard against hand-edit typos."""
    sources = load_sources()
    assert len(sources) > 20, "source list looks truncated"

    by_tier: dict[int, list[Source]] = {}
    for source in sources:
        by_tier.setdefault(source.tier, []).append(source)

    # All three tiers must be populated, or the digest would be lopsided.
    assert set(by_tier) == {1, 2, 3}

    # Tier 1 is the stated priority, so it must carry the highest weights.
    assert max(s.weight for s in by_tier[1]) >= max(s.weight for s in by_tier[3])

    # Every fragile source needs a note explaining why, so the next reader knows.
    for source in sources:
        if source.fragile:
            assert source.note or "mirror" in source.name.lower(), (
                f"{source.name}: fragile sources need a note explaining the risk"
            )
