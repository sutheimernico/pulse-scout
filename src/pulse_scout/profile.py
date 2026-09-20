"""Loading the relevance profile.

The profile is the answer to "what is this digest for", and it is a file rather than code so
that changing what reaches the Pflicht list is a reviewable diff. Like the source list it is
validated loudly on load: a typo in a weight would otherwise surface as a digest that is
subtly, unaccountably wrong — the worst possible failure for a product whose entire value is
that its reader can believe it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[2] / "data" / "profile.toml"

_REQUIRED_FACTORS = (
    "engagement",
    "keyword",
    "duplicate",
    "duplicate_cap",
    "recency_half_life_hours",
    "recency_floor",
    "recency_undated",
    "keyword_cap",
    "negative_penalty",
)


class ProfileError(ValueError):
    """The profile is malformed. Always fatal — a guessed default would be a silent lie."""


def _positive(values: dict[str, object], key: str) -> float:
    value = values.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ProfileError(f"factors.{key} must be a positive number, got {value!r}")
    return float(value)


def _terms(raw: object, section: str) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise ProfileError(f"[{section}] must be a non-empty table")
    terms: dict[str, float] = {}
    for term, weight in raw.items():
        if not isinstance(weight, int | float) or isinstance(weight, bool) or weight <= 0:
            raise ProfileError(f"[{section}] {term!r} must have a positive weight, got {weight!r}")
        terms[term.casefold()] = float(weight)
    return terms


def _compile(terms: dict[str, float]) -> re.Pattern[str]:
    """One alternation for the whole vocabulary — 130 separate searches per item would show.

    Longest first, so that "react aria" wins over "react" and claims the bigger weight.
    """
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(term) for term in ordered) + r")(?!\w)")


@dataclass(frozen=True, slots=True)
class Profile:
    """The tuning constants and the vocabulary, validated."""

    engagement: float
    keyword: float
    duplicate: float
    duplicate_cap: int
    recency_half_life_hours: float
    recency_floor: float
    recency_undated: float
    keyword_cap: float
    negative_penalty: float
    tier_bonus: dict[int, float]
    keywords: dict[str, float]
    negative_keywords: dict[str, float]
    _positive_pattern: re.Pattern[str]
    _negative_pattern: re.Pattern[str]

    def keyword_score(self, text: str) -> tuple[float, int]:
        """(capped positive score, number of distinct excluded topics matched)."""
        lowered = text.casefold()
        hits = {match.group(0) for match in self._positive_pattern.finditer(lowered)}
        score = min(sum(self.keywords[hit] for hit in hits), self.keyword_cap)
        misses = {match.group(0) for match in self._negative_pattern.finditer(lowered)}
        return score, len(misses)


def load_profile(path: Path | None = None) -> Profile:
    """Read and validate the relevance profile."""
    path = path or DEFAULT_PROFILE_PATH
    if not path.is_file():
        raise ProfileError(f"profile not found: {path}")

    with path.open("rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ProfileError(f"{path} is not valid TOML: {exc}") from exc

    factors = data.get("factors")
    if not isinstance(factors, dict):
        raise ProfileError(f"{path} has no [factors] table")
    missing = [key for key in _REQUIRED_FACTORS if key not in factors]
    if missing:
        raise ProfileError(f"[factors] is missing {', '.join(missing)}")

    raw_tiers = data.get("tier_bonus")
    if not isinstance(raw_tiers, dict):
        raise ProfileError(f"{path} has no [tier_bonus] table")
    tier_bonus: dict[int, float] = {}
    for key, value in raw_tiers.items():
        try:
            tier = int(key)
        except ValueError as exc:
            raise ProfileError(f"[tier_bonus] key {key!r} is not a tier number") from exc
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise ProfileError(f"[tier_bonus] {key} must be positive, got {value!r}")
        tier_bonus[tier] = float(value)
    if set(tier_bonus) != {1, 2, 3}:
        raise ProfileError(f"[tier_bonus] must cover tiers 1, 2 and 3, got {sorted(tier_bonus)}")

    keywords = _terms(data.get("keywords"), "keywords")
    negative = _terms(data.get("negative_keywords"), "negative_keywords")
    overlap = set(keywords) & set(negative)
    if overlap:
        raise ProfileError(f"terms are both wanted and excluded: {sorted(overlap)}")

    negative_penalty = _positive(factors, "negative_penalty")
    if negative_penalty >= 1:
        raise ProfileError("factors.negative_penalty must be below 1 — it is a penalty")
    recency_floor = _positive(factors, "recency_floor")
    if recency_floor >= 1:
        raise ProfileError("factors.recency_floor must be below 1")

    return Profile(
        engagement=_positive(factors, "engagement"),
        keyword=_positive(factors, "keyword"),
        duplicate=_positive(factors, "duplicate"),
        duplicate_cap=int(_positive(factors, "duplicate_cap")),
        recency_half_life_hours=_positive(factors, "recency_half_life_hours"),
        recency_floor=recency_floor,
        recency_undated=_positive(factors, "recency_undated"),
        keyword_cap=_positive(factors, "keyword_cap"),
        negative_penalty=negative_penalty,
        tier_bonus=tier_bonus,
        keywords=keywords,
        negative_keywords=negative,
        _positive_pattern=_compile(keywords),
        _negative_pattern=_compile(negative),
    )
