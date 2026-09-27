"""Loading and validating the source list.

The source list is the one piece of configuration a human edits by hand, and a typo in it
would otherwise surface as a confusing failure halfway through a pipeline run. So it is
validated on load, loudly.

TOML is read with the standard library, so this costs no dependency.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[2] / "data" / "sources.toml"

VALID_KINDS = frozenset({"rss", "atom", "json"})
VALID_TIERS = frozenset({1, 2, 3})


class ConfigError(ValueError):
    """The source list is malformed. Always fatal — never fall back to a default."""


@dataclass(frozen=True, slots=True)
class Source:
    """One configured feed or API endpoint."""

    name: str
    tier: int
    weight: float
    url: str
    kind: str
    abstract: bool
    signal: str | None = None
    note: str | None = None
    fragile: bool = False

    @property
    def tolerates_failure(self) -> bool:
        """Whether a failed fetch should be a warning rather than an error.

        Exactly one Nitter instance worked when the list was built, so those entries are
        expected to break eventually. Everything else failing means something we should notice.
        """
        return self.fragile


def _require(raw: dict[str, object], key: str, index: int) -> object:
    if key not in raw:
        raise ConfigError(f"source #{index}: missing required key {key!r}")
    return raw[key]


def parse_source(raw: dict[str, object], index: int) -> Source:
    """Build one Source from its TOML table, rejecting anything malformed."""
    name = _require(raw, "name", index)
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"source #{index}: 'name' must be a non-empty string")

    # bool is a subclass of int, so `True in {1, 2, 3}` is True. Reject it explicitly,
    # otherwise `tier = true` in the TOML would silently become tier 1.
    tier = _require(raw, "tier", index)
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in VALID_TIERS:
        raise ConfigError(f"{name!r}: 'tier' must be one of {sorted(VALID_TIERS)}, got {tier!r}")

    weight = _require(raw, "weight", index)
    if not isinstance(weight, int | float) or isinstance(weight, bool) or weight <= 0:
        raise ConfigError(f"{name!r}: 'weight' must be a positive number, got {weight!r}")

    url = _require(raw, "url", index)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ConfigError(f"{name!r}: 'url' must be an http(s) URL, got {url!r}")

    kind = _require(raw, "kind", index)
    if not isinstance(kind, str) or kind not in VALID_KINDS:
        raise ConfigError(f"{name!r}: 'kind' must be one of {sorted(VALID_KINDS)}, got {kind!r}")

    abstract = _require(raw, "abstract", index)
    if not isinstance(abstract, bool):
        raise ConfigError(f"{name!r}: 'abstract' must be a boolean, got {abstract!r}")

    signal = raw.get("signal")
    note = raw.get("note")
    fragile = raw.get("fragile", False)
    if not isinstance(fragile, bool):
        raise ConfigError(f"{name!r}: 'fragile' must be a boolean, got {fragile!r}")

    return Source(
        name=name,
        tier=tier,
        weight=float(weight),
        url=url,
        kind=kind,
        abstract=abstract,
        signal=str(signal) if signal is not None else None,
        note=str(note) if note is not None else None,
        fragile=fragile,
    )


def load_sources(path: Path | None = None) -> list[Source]:
    """Read and validate the source list.

    Raises ConfigError on anything malformed, including duplicate URLs — two entries pointing
    at the same feed would silently double that source's weight during ranking.
    """
    path = path or DEFAULT_SOURCES_PATH
    if not path.is_file():
        raise ConfigError(f"source list not found: {path}")

    with path.open("rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    raw_sources = data.get("source")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError(f"{path} contains no [[source]] entries")

    sources = [parse_source(raw, i) for i, raw in enumerate(raw_sources)]

    seen: dict[str, str] = {}
    for source in sources:
        if source.url in seen:
            raise ConfigError(f"duplicate url in {seen[source.url]!r} and {source.name!r}")
        seen[source.url] = source.name

    return sources


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=value` lines from a `.env` file; a missing file is simply empty.

    Twelve lines instead of python-dotenv. Only the web server reads this, for the phone token
    and the port; the systemd unit hands the same file over with `EnvironmentFile=`.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values
