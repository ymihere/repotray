"""IconSpec → theme icon name (symbolic mode)."""

from __future__ import annotations

from repotray.core.indicator import IconSpec

SYMBOLIC = ("foreground", "warning", "error", "success")
TINTS = ("warning", "error", "success")


def icon_name(spec: IconSpec) -> str:
    """Name of the shipped symbolic SVG for ``spec``. Hex colours are not representable here."""
    if spec.hex_mode:
        raise ValueError("hex colours need a full-colour icon (repotray.icons.svg)")
    if spec.state == "error":
        return "repotray-error-symbolic"
    if spec.state == "paused":
        return "repotray-paused-symbolic"
    name = "repotray"
    if spec.state == "attention":
        if spec.tint:
            if spec.tint not in TINTS:
                raise ValueError(f"unknown tint colour {spec.tint!r}")
            name += f"-tint-{spec.tint}"
        for corner, color in (("top", spec.top), ("bottom", spec.bottom)):
            if color:
                if color not in SYMBOLIC:
                    raise ValueError(f"unknown dot colour {color!r}")
                name += f"-{corner}-{color}"
    return name + "-symbolic"


def all_names() -> list[str]:
    names = []
    for tint in (None, *TINTS):
        for top in (None, *SYMBOLIC):
            for bottom in (None, *SYMBOLIC):
                state = "attention" if (tint or top or bottom) else "clean"
                names.append(icon_name(IconSpec(state, top, bottom, tint)))
    return [*names, "repotray-error-symbolic", "repotray-paused-symbolic"]
