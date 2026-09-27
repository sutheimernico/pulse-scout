"""The web app manifest must be installable: Chrome's checklist, checked without a browser."""

from __future__ import annotations

import json
import struct
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "frontend" / "public"
MANIFEST = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_the_manifest_has_what_install_requires() -> None:
    assert MANIFEST["name"] and MANIFEST["short_name"]
    assert MANIFEST["start_url"] == "/"
    assert MANIFEST["scope"] == "/"
    assert MANIFEST["display"] == "standalone"
    assert MANIFEST["lang"] == "de"


def test_every_icon_exists_at_the_size_it_claims() -> None:
    for icon in MANIFEST["icons"]:
        path = PUBLIC / icon["src"].lstrip("/")
        assert path.is_file(), icon["src"]
        width, height = png_size(path)
        assert icon["sizes"] == f"{width}x{height}", icon["src"]
        assert icon["type"] == "image/png"


def test_the_icons_chrome_insists_on_are_there() -> None:
    sizes = {icon["sizes"] for icon in MANIFEST["icons"] if icon.get("purpose") == "any"}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon.get("purpose") == "maskable" for icon in MANIFEST["icons"])


def test_the_worker_needs_no_build_step() -> None:
    """sw.js is copied as-is; it may import nothing but its sibling strategy module."""
    source = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith("} from ")]
    assert imports == ['} from "./sw-strategy.js";']
