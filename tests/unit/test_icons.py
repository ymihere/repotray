import importlib.util
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from repotray.core.indicator import IconSpec
from repotray.icons import data_dir, geometry, symbolic_dir
from repotray.icons.names import all_names, icon_name
from repotray.icons.svg import render_svg, write_hex_icon

SVG_NS = "{http://www.w3.org/2000/svg}"
ROOT = Path(__file__).resolve().parents[2]
NAME_RE = re.compile(
    r"repotray(?:-tint-(?P<tint>\w+))?(?:-top-(?P<top>\w+))?(?:-bottom-(?P<bottom>\w+))?-symbolic"
)


def svgs():
    return sorted(symbolic_dir().glob("*.svg"))


def test_all_files_exist_and_parse():
    files = svgs()
    assert len(files) == 102
    assert {f.stem for f in files} == set(all_names())
    for f in files:
        assert f.stat().st_size < 4096
        root = ET.parse(f).getroot()
        assert root.tag == f"{SVG_NS}svg"
        assert root.get("viewBox") == "0 0 16 16"
        assert root.get("width") == "16" and root.get("height") == "16"
        text = f.read_text()
        assert "mask" not in text and "clip" not in text and "metadata" not in text


def path_points(d: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[::2], nums[1::2], strict=True))


@pytest.mark.parametrize("f", svgs(), ids=lambda f: f.stem)
def test_dots_and_knockouts(f):
    root = ET.parse(f).getroot()
    circles = root.findall(f"{SVG_NS}circle")
    glyph = root.findall(f"{SVG_NS}path")[0]
    m = NAME_RE.fullmatch(f.stem)
    if m is None:  # error / paused: bottom-right knockout, no circles
        assert not circles
        shown = {"bottom"}
    else:
        shown = {k for k in ("top", "bottom") if m.group(k)}
        by_cy = {c.get("cy"): c for c in circles}
        assert len(circles) == len(shown)
        for corner, cy in (("top", "3"), ("bottom", "13")):
            color = m.group(corner)
            if color:
                c = by_cy[cy]
                assert c.get("cx") == "13" and c.get("r") == "3"
                assert c.get("class") == (None if color == "foreground" else color)
        tint = m.group("tint")
        assert glyph.get("class") == tint
    centers = {"top": (13, 3), "bottom": (13, 13)}
    for x, y in path_points(glyph.get("d")):
        for corner in shown:
            cx, cy = centers[corner]
            assert math.hypot(x - cx, y - cy) >= 3.9, (f.stem, x, y)


def test_error_and_paused_marks():
    err = ET.parse(symbolic_dir() / "repotray-error-symbolic.svg").getroot()
    paths = err.findall(f"{SVG_NS}path")
    assert len(paths) == 2 and paths[1].get("class") == "error"
    paused = ET.parse(symbolic_dir() / "repotray-paused-symbolic.svg").getroot()
    assert len(paused.findall(f"{SVG_NS}path")) == 2


@pytest.mark.skipif(
    not (importlib.util.find_spec("shapely") and importlib.util.find_spec("svgpathtools")),
    reason="build dependencies missing",
)
def test_regenerated_output_matches_committed(tmp_path):
    subprocess.run(
        [sys.executable, str(ROOT / "tools/build_icons.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    # GEOS builds differ in the last digits, so compare shapes, not bytes.
    for f in svgs():
        new = tmp_path / "symbolic" / f.name
        assert svg_structure(new) == svg_structure(f), f.name
        for a, b in zip(svg_shapes(new), svg_shapes(f), strict=True):
            assert a.symmetric_difference(b).area < 0.01, f.name
    assert len(list((tmp_path / "symbolic").iterdir())) == 102
    old = json.loads((data_dir() / "geometry.json").read_text("utf-8"))
    new = json.loads((tmp_path / "geometry.json").read_text("utf-8"))
    assert old.keys() == new.keys() and old["dots"] == new["dots"]


def svg_structure(path: Path) -> list[tuple]:
    """Element tags and attributes other than path data."""
    root = ET.parse(path).getroot()
    return [(el.tag, sorted((k, v) for k, v in el.attrib.items() if k != "d")) for el in root]


def svg_shapes(path: Path) -> list:
    """Each <path> as a shapely geometry (even-odd fill)."""
    from shapely.geometry import Polygon

    shapes = []
    for el in ET.parse(path).getroot().findall(f"{SVG_NS}path"):
        shape = Polygon()
        for ring in re.findall(r"M([^Z]+)Z", el.get("d")):
            nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", ring)]
            pts = list(zip(nums[::2], nums[1::2], strict=True))
            shape = shape.symmetric_difference(Polygon(pts).buffer(0))
        shapes.append(shape)
    return shapes


def test_names_for_every_spec():
    assert icon_name(IconSpec()) == "repotray-symbolic"
    assert icon_name(IconSpec("attention", "success", "warning")) == (
        "repotray-top-success-bottom-warning-symbolic"
    )
    assert icon_name(IconSpec("attention", None, None, "error")) == "repotray-tint-error-symbolic"
    assert icon_name(IconSpec("error", "success")) == "repotray-error-symbolic"
    assert icon_name(IconSpec("paused")) == "repotray-paused-symbolic"
    with pytest.raises(ValueError):
        icon_name(IconSpec("attention", "#ff0000"))


def test_hex_svg(tmp_path):
    spec = IconSpec("attention", "#ff0000", "warning", None, glyph_color="#123456")
    text = render_svg(spec)
    assert 'fill="#123456"' in text and 'fill="#ff0000"' in text and 'fill="#f57900"' in text
    assert "class=" not in text
    p = write_hex_icon(spec, tmp_path)
    assert "symbolic" not in p.name and p.name.startswith("icon-")
    assert write_hex_icon(spec, tmp_path) == p
    ET.fromstring(p.read_text())


def test_geometry_shape():
    g = geometry()
    assert set(g["glyph"]) == {"none", "top", "bottom", "both"}
    assert g["dots"]["bottom"] == [13.0, 13.0, 3.0]


def test_raster():
    pytest.importorskip("PIL")
    from repotray.icons.raster import render

    img = render(IconSpec("attention", "success", "warning"), size=64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((52, 12)) == (46, 194, 126, 255)  # top dot centre
    assert img.getpixel((52, 52)) == (245, 121, 0, 255)  # bottom dot centre
    assert img.getpixel((0, 0))[3] == 0  # transparent corner
    # The book's right edge at y = 9.5 is cut away in the ring around the bottom dot.
    assert render(IconSpec(), size=64).getpixel((54, 38))[3] > 200
    assert img.getpixel((54, 38))[3] < 16
    err = render(IconSpec("error"), size=64, glyph_color="#000000")
    assert err.getpixel((52, 52))[:3] == (224, 27, 36)
