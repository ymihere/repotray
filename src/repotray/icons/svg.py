"""IconSpec → full-colour SVG (hex mode): literal fills, so the panel shows it as-is.

The file name never contains "symbolic": the Cinnamon applet would recolour it otherwise.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from repotray.core.indicator import IconSpec
from repotray.icons import geometry


def _num(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def path_d(rings: list) -> str:
    parts = []
    for poly in rings:
        for ring in poly:
            (x0, y0), rest = ring[0], ring[1:]
            pts = " ".join(f"{_num(x)} {_num(y)}" for x, y in rest)
            parts.append(f"M{_num(x0)} {_num(y0)}L{pts}Z")
    return "".join(parts)


def resolve(color: str | None, glyph_color: str) -> str:
    """Theme class name or hex → literal colour. None/foreground → the glyph colour."""
    if color is None or color == "foreground":
        return glyph_color
    if color.startswith("#"):
        return color
    return geometry()["fallback"][color]


def variant(spec: IconSpec) -> str:
    if spec.state in ("error", "paused"):
        return "bottom"
    top, bottom = bool(spec.top), bool(spec.bottom)
    return {(False, False): "none", (True, False): "top", (False, True): "bottom"}.get(
        (top, bottom), "both"
    )


def render_svg(spec: IconSpec) -> str:
    g = geometry()
    glyph = resolve(spec.tint, spec.glyph_color)
    els = [f'<path d="{path_d(g["glyph"][variant(spec)])}" fill-rule="evenodd" fill="{glyph}"/>']
    if spec.state == "error":
        els.append(f'<path d="{path_d(g["cross"])}" fill="{resolve("error", spec.glyph_color)}"/>')
    elif spec.state == "paused":
        els.append(f'<path d="{path_d(g["bars"])}" fill="{spec.glyph_color}"/>')
    else:
        for corner, color in (("top", spec.top), ("bottom", spec.bottom)):
            if color:
                cx, cy, r = g["dots"][corner]
                fill = resolve(color, spec.glyph_color)
                els.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{fill}"/>')
    body = "\n".join(els)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">\n'
        f"{body}\n</svg>\n"
    )


def write_hex_icon(spec: IconSpec, cache_dir: Path) -> Path:
    """Write the full-colour SVG to ``cache_dir/icon-<sha1>.svg`` (idempotent) and return it."""
    text = render_svg(spec)
    digest = hashlib.sha1(text.encode()).hexdigest()[:12]
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"icon-{digest}.svg"
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, "utf-8")
        tmp.replace(path)
    return path
