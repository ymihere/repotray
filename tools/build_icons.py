#!/usr/bin/env python3
"""Build repotray's tray icons from the Octicon `repo` glyph (dev-only; output is committed).

The corner-dot knockouts are baked into the glyph path (boolean difference), never done with masks
or clip paths: GTK's symbolic loader recolours every element, which would recolour a mask too.

Outputs, in ``--out`` (default: src/repotray/icons/data):
  symbolic/repotray[-tint-<t>][-top-<c>][-bottom-<c>]-symbolic.svg   100 files
  symbolic/repotray-error-symbolic.svg, symbolic/repotray-paused-symbolic.svg
  geometry.json        rings for full-colour (hex) SVGs and Pillow rasters
  LICENSE-octicons     the upstream MIT notice

Needs: shapely>=2, svgpathtools (both in the `dev` extra).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from itertools import product
from pathlib import Path

from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union
from svgpathtools import Line, parse_path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GLYPH_SVG = HERE / "octicons" / "repo-16.svg"
LICENSE = HERE / "octicons" / "LICENSE"
DEFAULT_OUT = ROOT / "src" / "repotray" / "icons" / "data"

# Glyph transform: scale about the centre, then offset. Verified in the live tray at 1.0 / 0.
GLYPH_SCALE = 1.0
GLYPH_CENTER = (8.0, 8.0)
GLYPH_OFFSET = (0.0, 0.0)

FLATTEN = 0.05  # max segment length when flattening curves
SIMPLIFY = 0.01
DIGITS = 3

DOT_R = 3.0
KNOCKOUT_R = 4.0
DOTS = {"top": (13.0, 3.0), "bottom": (13.0, 13.0)}

FALLBACK = {
    "foreground": "#bebebe",
    "warning": "#f57900",
    "error": "#e01b24",
    "success": "#2ec27e",
}
TINTS = (None, "warning", "error", "success")
DOT_COLORS = (None, "foreground", "warning", "error", "success")


# --- geometry -----------------------------------------------------------------------------------


def flatten(seg) -> list[tuple[float, float]]:
    if isinstance(seg, Line):
        pts = [seg.start, seg.end]
    else:
        n = max(2, math.ceil(seg.length() / FLATTEN))
        pts = [seg.point(i / n) for i in range(n + 1)]
    return [(p.real, p.imag) for p in pts]


def glyph_shape() -> MultiPolygon:
    d = re.search(r'\sd="([^"]+)"', GLYPH_SVG.read_text()).group(1)
    path = parse_path(d)
    shape = Polygon()
    for sub in path.continuous_subpaths():
        pts: list[tuple[float, float]] = []
        for seg in sub:
            fl = flatten(seg)
            pts.extend(fl if not pts else fl[1:])
        poly = Polygon(pts).buffer(0)
        shape = shape.symmetric_difference(poly)  # even-odd fill
    shape = affinity.scale(shape, GLYPH_SCALE, GLYPH_SCALE, origin=GLYPH_CENTER)
    shape = affinity.translate(shape, *GLYPH_OFFSET)
    return _multi(shape)


def _multi(g) -> MultiPolygon:
    if isinstance(g, Polygon):
        return MultiPolygon([g]) if not g.is_empty else MultiPolygon()
    if isinstance(g, MultiPolygon):
        return g
    return MultiPolygon([p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)])


def knockout(shape, corners: tuple[str, ...]) -> MultiPolygon:
    for c in corners:
        shape = shape.difference(Point(*DOTS[c]).buffer(KNOCKOUT_R, quad_segs=32))
    return _multi(shape.simplify(SIMPLIFY, preserve_topology=True))


def cross_shape() -> MultiPolygon:
    cx, cy = DOTS["bottom"]
    bar = box(cx - 2.5, cy - 0.75, cx + 2.5, cy + 0.75)
    x = unary_union([affinity.rotate(bar, 45, (cx, cy)), affinity.rotate(bar, -45, (cx, cy))])
    return _multi(x.simplify(SIMPLIFY))


def bars_shape() -> MultiPolygon:
    return _multi(unary_union([box(11.0, 10.5, 12.25, 15.5), box(13.75, 10.5, 15.0, 15.5)]))


def rings(shape: MultiPolygon) -> list[list[list[list[float]]]]:
    """[polygon][ring][point] = [x, y], rounded; exterior first, then holes."""
    out = []
    for poly in shape.geoms:
        rs = [poly.exterior, *poly.interiors]
        out.append([[[round(x, DIGITS), round(y, DIGITS)] for x, y in r.coords[:-1]] for r in rs])
    return out


def path_d(rs) -> str:
    def num(v: float) -> str:
        s = f"{v:.{DIGITS}f}".rstrip("0").rstrip(".")
        return "0" if s == "-0" else s

    parts = []
    for poly in rs:
        for ring in poly:
            (x0, y0), rest = ring[0], ring[1:]
            pts = " ".join(f"{num(x)} {num(y)}" for x, y in rest)
            parts.append(f"M{num(x0)} {num(y0)}L{pts}Z")
    return "".join(parts)


# --- SVG ----------------------------------------------------------------------------------------


def fill_attrs(color: str | None) -> str:
    if color is None or color == "foreground":
        return f'style="fill:{FALLBACK["foreground"]}"'
    return f'class="{color}" style="fill:{FALLBACK[color]}"'


def svg(elements: list[str]) -> str:
    body = "\n".join(elements)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">\n'
        f"{body}\n</svg>\n"
    )


def glyph_el(d: str, tint: str | None) -> str:
    return f'<path d="{d}" fill-rule="evenodd" {fill_attrs(tint)}/>'


def dot_el(corner: str, color: str) -> str:
    cx, cy = DOTS[corner]
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{DOT_R:g}" {fill_attrs(color)}/>'


def icon_name(tint: str | None, top: str | None, bottom: str | None) -> str:
    name = "repotray"
    if tint:
        name += f"-tint-{tint}"
    if top:
        name += f"-top-{top}"
    if bottom:
        name += f"-bottom-{bottom}"
    return name + "-symbolic"


def build(out: Path) -> list[Path]:
    base = glyph_shape()
    variants = {
        "none": knockout(base, ()),
        "top": knockout(base, ("top",)),
        "bottom": knockout(base, ("bottom",)),
        "both": knockout(base, ("top", "bottom")),
    }
    vrings = {k: rings(v) for k, v in variants.items()}
    d = {k: path_d(r) for k, r in vrings.items()}
    cross, bars = rings(cross_shape()), rings(bars_shape())

    sym = out / "symbolic"
    if sym.exists():
        shutil.rmtree(sym)
    sym.mkdir(parents=True)
    written: list[Path] = []

    for tint, top, bottom in product(TINTS, DOT_COLORS, DOT_COLORS):
        key = {(False, False): "none", (True, False): "top", (False, True): "bottom"}.get(
            (bool(top), bool(bottom)), "both"
        )
        els = [glyph_el(d[key], tint)]
        if top:
            els.append(dot_el("top", top))
        if bottom:
            els.append(dot_el("bottom", bottom))
        f = sym / f"{icon_name(tint, top, bottom)}.svg"
        f.write_text(svg(els))
        written.append(f)

    f = sym / "repotray-error-symbolic.svg"
    f.write_text(
        svg([glyph_el(d["bottom"], None), f'<path d="{path_d(cross)}" {fill_attrs("error")}/>'])
    )
    written.append(f)
    f = sym / "repotray-paused-symbolic.svg"
    f.write_text(
        svg([glyph_el(d["bottom"], None), f'<path d="{path_d(bars)}" {fill_attrs(None)}/>'])
    )
    written.append(f)

    geometry = {
        "viewbox": 16,
        "glyph": vrings,
        "dots": {k: [*v, DOT_R] for k, v in DOTS.items()},
        "knockout_radius": KNOCKOUT_R,
        "cross": cross,
        "bars": bars,
        "fallback": FALLBACK,
        "source": "Octicons repo-16 (MIT), see LICENSE-octicons",
    }
    (out / "geometry.json").write_text(json.dumps(geometry, separators=(",", ":")) + "\n")
    shutil.copyfile(LICENSE, out / "LICENSE-octicons")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    files = build(args.out)
    print(f"wrote {len(files)} SVGs, geometry.json and LICENSE-octicons to {args.out}")


if __name__ == "__main__":
    main()
