"""IconSpec → Pillow RGBA image, for backends that need pixmaps (pystray on macOS/Windows).

Drawn at 4× from geometry.json and downsampled with LANCZOS.
"""

from __future__ import annotations

from repotray.core.indicator import IconSpec
from repotray.icons import geometry
from repotray.icons.svg import resolve, variant

SUPERSAMPLE = 4


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mask(rings: list, px: int, scale: float):
    from PIL import Image, ImageDraw

    mask = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(mask)

    def area(poly):
        ring = poly[0]
        return abs(
            sum(
                x0 * y1 - x1 * y0
                for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True)
            )
        )

    for poly in sorted(rings, key=area, reverse=True):
        for i, ring in enumerate(poly):
            pts = [(x * scale, y * scale) for x, y in ring]
            draw.polygon(pts, fill=255 if i == 0 else 0)
    return mask


def render(spec: IconSpec, size: int = 64, glyph_color: str | None = None):
    """RGBA image of ``size`` px. ``glyph_color`` overrides the foreground (light/dark bars)."""
    from PIL import Image, ImageDraw

    g = geometry()
    fg = glyph_color or spec.glyph_color
    px = size * SUPERSAMPLE
    scale = px / g["viewbox"]
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))

    def paint(mask, color: str) -> None:
        layer = Image.new("RGBA", (px, px), (*_rgb(color), 255))
        img.paste(layer, (0, 0), mask)

    paint(_mask(g["glyph"][variant(spec)], px, scale), resolve(spec.tint, fg))
    if spec.state == "error":
        paint(_mask(g["cross"], px, scale), resolve("error", fg))
    elif spec.state == "paused":
        paint(_mask(g["bars"], px, scale), fg)
    else:
        for corner, color in (("top", spec.top), ("bottom", spec.bottom)):
            if color:
                cx, cy, r = g["dots"][corner]
                mask = Image.new("L", (px, px), 0)
                ImageDraw.Draw(mask).ellipse(
                    [(cx - r) * scale, (cy - r) * scale, (cx + r) * scale, (cy + r) * scale],
                    fill=255,
                )
                paint(mask, resolve(color, fg))
    return img.resize((size, size), Image.LANCZOS)
