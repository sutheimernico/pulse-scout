#!/usr/bin/env python3
"""Draw the PWA icons: a pulse line on the accent green. Standard library only.

    uv run python scripts/make_icons.py

Writes frontend/public/icons/icon-192.png and icon-512.png. The line stays inside the
central 60 %, so the same image is also a valid maskable icon (safe zone: a 40 % radius).
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "icons"

BACKGROUND = (0x0F, 0x7A, 0x5C)
LINE = (0xFF, 0xFF, 0xFF)
# The pulse, in unit coordinates.
POINTS = [(0.20, 0.54), (0.38, 0.54), (0.45, 0.32), (0.53, 0.72), (0.60, 0.46), (0.64, 0.54),
          (0.80, 0.54)]
HALF_WIDTH = 0.035


def _distance(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _png(size: int) -> bytes:
    rows = bytearray()
    segments = list(zip(POINTS, POINTS[1:], strict=False))
    for y in range(size):
        rows.append(0)  # filter type: none
        for x in range(size):
            px, py = (x + 0.5) / size, (y + 0.5) / size
            d = min(_distance(px, py, a, b) for a, b in segments)
            cover = max(0.0, min(1.0, (HALF_WIDTH - d) * size + 0.5))
            rows.extend(
                round(bg + (fg - bg) * cover) for bg, fg in zip(BACKGROUND, LINE, strict=True)
            )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = OUT / f"icon-{size}.png"
        path.write_bytes(_png(size))
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
