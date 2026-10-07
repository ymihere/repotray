"""IconSpec → theme icon name (symbolic mode)."""

from __future__ import annotations

from repotray.core.indicator import IconSpec

SYMBOLIC = ("foreground", "warning", "error", "success")
TINTS = ("warning", "error", "success")
MARKERS = ("arrow", "dot")
# Name parts for the top and bottom corner, per marker shape.
CORNER_WORDS = {"dot": ("top", "bottom"), "arrow": ("up", "down")}


def icon_name(spec: IconSpec) -> str:
    """Name of the shipped symbolic SVG for ``spec``. Hex colours are not representable here."""
    if spec.hex_mode:
        raise ValueError("hex colours need a full-colour icon (repotray.icons.svg)")
    if spec.state == "error":
        return "repotray-error-symbolic"
    if spec.state == "paused":
        return "repotray-paused-symbolic"
    if spec.marker not in CORNER_WORDS:
        raise ValueError(f"unknown marker {spec.marker!r}")
    name = "repotray"
    if spec.state == "attention":
        if spec.tint:
            if spec.tint not in TINTS:
                raise ValueError(f"unknown tint colour {spec.tint!r}")
            name += f"-tint-{spec.tint}"
        for word, color in zip(CORNER_WORDS[spec.marker], (spec.top, spec.bottom), strict=True):
            if color:
                if color not in SYMBOLIC:
                    raise ValueError(f"unknown marker colour {color!r}")
                name += f"-{word}-{color}"
    return name + "-symbolic"


def all_names() -> list[str]:
    names: list[str] = []
    for marker in MARKERS:
        for tint in (None, *TINTS):
            for top in (None, *SYMBOLIC):
                for bottom in (None, *SYMBOLIC):
                    state = "attention" if (tint or top or bottom) else "clean"
                    names.append(icon_name(IconSpec(state, top, bottom, tint, marker=marker)))
    unique = list(dict.fromkeys(names))  # marker-less icons are shared by both shapes
    return [*unique, "repotray-error-symbolic", "repotray-paused-symbolic"]
