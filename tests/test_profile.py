"""Tests for the relevance profile loader.

`test_the_shipped_profile_matches_the_corrected_topic_set` is the important one: spec §1 and §4
still describe Nico as a data/BI developer, which decision D7 explicitly revokes. If the
profile ever drifts back to that premise, this test fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse_scout.profile import Profile, ProfileError, load_profile

MINIMAL = """
[factors]
engagement = 0.4
keyword = 0.3
duplicate = 0.25
duplicate_cap = 4
recency_half_life_hours = 24.0
recency_floor = 0.15
recency_undated = 0.55
keyword_cap = 4.0
negative_penalty = 0.35

[tier_bonus]
1 = 1.6
2 = 1.2
3 = 1.0

[keywords]
fastapi = 3.0
"react aria" = 3.0
react = 2.5

[negative_keywords]
dbt = 1.0
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "profile.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_minimal_profile_loads(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, MINIMAL))
    assert profile.tier_bonus == {1: 1.6, 2: 1.2, 3: 1.0}
    assert profile.keywords["fastapi"] == 3.0


def test_keyword_scoring_prefers_the_longest_match(tmp_path: Path) -> None:
    """'React Aria' must claim its own weight instead of matching the shorter 'react'."""
    profile = load_profile(write(tmp_path, MINIMAL))
    score, _ = profile.keyword_score("React Aria Components 1.0 released")
    assert score == 3.0


def test_keyword_scoring_respects_word_boundaries(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, MINIMAL))
    assert profile.keyword_score("reactive programming")[0] == 0.0
    assert profile.keyword_score("A React release")[0] == 2.5


def test_keyword_scoring_is_capped(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, MINIMAL))
    score, _ = profile.keyword_score("FastAPI and React Aria and React together")
    assert score == profile.keyword_cap


def test_negative_terms_are_counted_separately(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, MINIMAL))
    score, misses = profile.keyword_score("dbt 2.0 ships with FastAPI support")
    assert misses == 1
    assert score == 3.0


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ('engagement = 0.4', 'engagement = 0'),
        ('keyword_cap = 4.0', 'keyword_cap = -1'),
        ('negative_penalty = 0.35', 'negative_penalty = 1.5'),
        ('recency_floor = 0.15', 'recency_floor = 2.0'),
    ],
)
def test_bad_factors_are_rejected(tmp_path: Path, mutation: str, expected: str) -> None:
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path, MINIMAL.replace(mutation, expected)))


def test_a_missing_tier_is_rejected(tmp_path: Path) -> None:
    broken = MINIMAL.replace("3 = 1.0\n", "")
    with pytest.raises(ProfileError, match="tiers 1, 2 and 3"):
        load_profile(write(tmp_path, broken))


def test_a_term_cannot_be_both_wanted_and_excluded(tmp_path: Path) -> None:
    broken = MINIMAL.replace("[negative_keywords]\ndbt = 1.0", "[negative_keywords]\nreact = 1.0")
    with pytest.raises(ProfileError, match="both wanted and excluded"):
        load_profile(write(tmp_path, broken))


def test_a_missing_section_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match=r"\[factors\]"):
        load_profile(write(tmp_path, "[keywords]\nx = 1.0\n"))


def test_a_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="not found"):
        load_profile(tmp_path / "nope.toml")


def test_the_shipped_profile_loads() -> None:
    profile = load_profile()
    assert isinstance(profile, Profile)
    assert len(profile.keywords) > 40


def test_the_shipped_profile_matches_the_corrected_topic_set() -> None:
    """D7: fullstack and architecture, from a real fullstack stack — not data engineering."""
    profile = load_profile()

    for wanted in ("fastapi", "sqlmodel", "alembic", "react 19", "react aria", "pulumi",
                   "container apps", "azure devops", "anthropic", "architecture"):
        assert wanted in profile.keywords, f"{wanted} belongs in tier 1 per D7"

    for excluded in ("dbt", "databricks", "terraform", "kubernetes", "sql server", "power bi"):
        assert excluded in profile.negative_keywords, f"{excluded} was removed by D5/D7"
        assert excluded not in profile.keywords
