"""Backend discovery, probing and selection.

Built-ins are lazy import strings, so importing this module never imports a toolkit. Third-party
backends register a class under the ``repotray.backends`` entry point group.
"""

from __future__ import annotations

import importlib
import logging
import os
from importlib.metadata import entry_points

from repotray.backends.base import ProbeResult

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "repotray.backends"

BUILTINS: dict[str, str] = {
    "xapp": "repotray.backends.xapp:XAppBackend",
    "appindicator": "repotray.backends.appindicator:AppIndicatorBackend",
    "gtkstatusicon": "repotray.backends.gtkstatusicon:GtkStatusIconBackend",
    "pystray": "repotray.backends.pystray_backend:PystrayBackend",
    "fake": "repotray.backends.fake:FakeBackend",
}

NEVER_AUTO = {"fake"}


class BackendError(Exception):
    pass


def _load_target(target: str):
    module, _, attr = target.partition(":")
    return getattr(importlib.import_module(module), attr)


def available() -> dict[str, object]:
    """name → import string (built-in) or EntryPoint (plugin). Built-ins win on name clashes."""
    found: dict[str, object] = {}
    try:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            found[ep.name] = ep
    except Exception:  # pragma: no cover - broken metadata must not break the tray
        log.exception("reading entry points failed")
    found.update(BUILTINS)
    return found


def load(name: str):
    spec = available().get(name)
    if spec is None:
        raise BackendError(f"unknown backend '{name}' (known: {', '.join(sorted(available()))})")
    if isinstance(spec, str):
        return _load_target(spec)
    return spec.load()


def probe(name: str, platform) -> ProbeResult:
    try:
        cls = load(name)
        result = cls.probe(platform)
    except Exception as exc:  # import errors, missing typelibs, …
        return ProbeResult(0, f"{type(exc).__name__}: {exc}")
    if name in NEVER_AUTO:
        return ProbeResult(0, f"never auto-selected ({result.reason})")
    return result


def probe_all(platform) -> list[tuple[str, ProbeResult]]:
    return [(name, probe(name, platform)) for name in available()]


def requested(config_backend: str = "auto", cli_backend: str | None = None) -> str | None:
    for choice in (cli_backend, os.environ.get("REPOTRAY_BACKEND"), config_backend):
        if choice and choice != "auto":
            return choice
    return None


def select(platform, config_backend: str = "auto", cli_backend: str | None = None):
    """Return (name, class). Explicit choice > highest probe score > 0."""
    want = requested(config_backend, cli_backend)
    if want:
        return want, load(want)
    results = probe_all(platform)
    best = max(results, key=lambda r: r[1].score, default=None)
    if best is None or best[1].score <= 0:
        reasons = "; ".join(f"{n}: {r.reason}" for n, r in results)
        raise BackendError(f"no usable tray backend ({reasons})")
    return best[0], load(best[0])


def describe(platform, config_backend: str = "auto", cli_backend: str | None = None):
    """(chosen name or None, [(name, score, reason)]) for `repotray doctor`."""
    results = probe_all(platform)
    rows = [(n, r.score, r.reason) for n, r in results]
    want = requested(config_backend, cli_backend)
    if want:
        return want, rows
    best = max(results, key=lambda r: r[1].score, default=None)
    return (best[0] if best and best[1].score > 0 else None), rows
