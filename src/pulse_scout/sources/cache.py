"""Where raw feed bodies live — and why they live nowhere else.

Raw feed content is third-party copyrighted material (constraint C4). It is useful to keep for
a while: it makes a parser bug reproducible without re-fetching, and it lets a run be replayed
offline. But it must never reach a commit. So it goes to `.cache/raw/`, which is gitignored,
and this module physically refuses to write anywhere else — a gitignore entry protects against
carelessness, a path guard protects against a bug.

Only the body is cached here. HTTP validators (ETag, Last-Modified) belong to the SQLite store
with the rest of the per-source state; keeping them in two places would guarantee they drift.
"""

from __future__ import annotations

import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[3] / ".cache" / "raw"
DEFAULT_MAX_AGE_DAYS = 14

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_EXTENSIONS = {"rss": "xml", "atom": "xml", "json": "json"}


class CacheError(RuntimeError):
    """A cache operation tried to leave the cache directory."""


def slugify(name: str) -> str:
    """A filesystem-safe stem for a source name."""
    slug = _SLUG_STRIP.sub("-", name.casefold()).strip("-")
    if not slug:
        raise CacheError(f"source name {name!r} has no usable characters for a filename")
    return slug


class RawCache:
    """Raw bodies on disk, one directory per day."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or DEFAULT_CACHE_ROOT).resolve()

    def _checked(self, path: Path) -> Path:
        """Refuse any path that resolves outside the cache root."""
        resolved = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise CacheError(f"refusing to touch {resolved} — outside the cache root {self.root}")
        return resolved

    def path_for(self, source_name: str, *, kind: str = "rss", when: date | None = None) -> Path:
        day = (when or datetime.now().date()).isoformat()
        extension = _EXTENSIONS.get(kind, "txt")
        return self._checked(Path(day) / f"{slugify(source_name)}.{extension}")

    def store(
        self, source_name: str, body: bytes, *, kind: str = "rss", when: date | None = None
    ) -> Path:
        path = self.path_for(source_name, kind=kind, when=when)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def load(
        self, source_name: str, *, kind: str = "rss", when: date | None = None
    ) -> bytes | None:
        path = self.path_for(source_name, kind=kind, when=when)
        return path.read_bytes() if path.is_file() else None

    def prune(self, *, max_age_days: int = DEFAULT_MAX_AGE_DAYS, today: date | None = None) -> int:
        """Delete day directories older than `max_age_days`. Returns how many went."""
        if not self.root.is_dir():
            return 0
        cutoff = (today or datetime.now().date()) - timedelta(days=max_age_days)
        removed = 0
        for entry in sorted(self.root.iterdir()):
            # Anything that is not a YYYY-MM-DD directory was not written by us. Leave it.
            if not entry.is_dir() or not _DAY_DIR.match(entry.name):
                continue
            try:
                day = date.fromisoformat(entry.name)
            except ValueError:  # pragma: no cover — the regex already guarantees this
                continue
            if day < cutoff:
                shutil.rmtree(self._checked(entry))
                removed += 1
        return removed
