"""Configuration: schema, defaults, validation, loading and change detection."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from importlib import resources
from pathlib import Path
from typing import Any

TRIGGERS = ("push", "pull", "dirty")
SYMBOLIC_COLORS = ("foreground", "warning", "error", "success")
TINT_COLORS = ("warning", "error", "success")
MARKERS = ("arrow", "dot")
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

DEFAULT_EXCLUDE_DIRS = (
    "node_modules",
    "vendor",
    "target",
    "build",
    "dist",
    "venv",
    "__pycache__",
    "snap",
    "Library",
    "AppData",
)


@dataclass(frozen=True, slots=True)
class IndicatorConfig:
    label: tuple[str, ...] = ("push", "pull")
    top_dot: tuple[str, ...] = ("push",)
    top_dot_color: str = "warning"
    bottom_dot: tuple[str, ...] = ("pull",)
    bottom_dot_color: str = "warning"
    tint: tuple[str, ...] = ()
    tint_color: str = "warning"
    glyph_color: str = "#e1e1e1"
    marker: str = "arrow"


@dataclass(frozen=True, slots=True)
class RepoOverride:
    fetch: bool = True
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    roots: tuple[str, ...] = ("~",)
    repos: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    max_depth: int = 4
    descend_into_repos: bool = False
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    status_interval: int = 60
    fetch_interval: int = 600
    rescan_interval: int = 600
    workers: int = 4
    fetch_workers: int = 4
    fetch_timeout: int = 60
    action_timeout: int = 120
    count_untracked_as_dirty: bool = True
    count_no_upstream_as_push: bool = False
    notifications: bool = False
    sync_strategy: str = "rebase"
    terminal: str = ""
    file_manager: str = ""
    editor: str = ""
    backend: str = "auto"
    panel_theme: str = "auto"
    panel_sort: str = "name"
    log_level: str = "info"
    indicator: IndicatorConfig = field(default_factory=IndicatorConfig)
    repo: dict[str, RepoOverride] = field(default_factory=dict)

    def override_for(self, path: Path) -> RepoOverride | None:
        """The ``[repo."<path>"]`` table that names this repository, if any."""
        for key, ov in self.repo.items():
            try:
                if expand(key).resolve() == path:
                    return ov
            except OSError:
                continue
        return None

    def scan_key(self) -> tuple:
        """Everything that, when changed, requires a rescan."""
        return (
            self.roots,
            self.repos,
            self.ignore,
            self.max_depth,
            self.descend_into_repos,
            self.exclude_dirs,
            tuple(sorted((k, v.fetch, v.name) for k, v in self.repo.items())),
        )


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


def abbreviate(path: Path) -> str:
    """``path`` for display, the home directory written as ``~`` (``~/code/x``; on Windows
    ``~\\code\\x``, one kind of slash)."""
    home = Path.home()
    if path == home:
        return "~"
    try:
        return "~" + os.sep + str(path.relative_to(home))
    except ValueError:
        return str(path)


# key -> (kind, validator description). Kinds: int ranges, bool, str choices, list[str].
_INT_RANGES: dict[str, tuple[int, int | None]] = {
    "max_depth": (0, 12),
    "status_interval": (10, None),
    "fetch_interval": (60, None),
    "rescan_interval": (60, None),
    "workers": (1, 32),
    "fetch_workers": (1, 32),
    "fetch_timeout": (5, 600),
    "action_timeout": (10, 1800),
}
_BOOLS = (
    "descend_into_repos",
    "count_untracked_as_dirty",
    "count_no_upstream_as_push",
    "notifications",
)
_STR_CHOICES: dict[str, tuple[str, ...] | None] = {
    "sync_strategy": ("rebase", "merge"),
    "terminal": None,
    "file_manager": None,
    "editor": None,
    "backend": None,
    "panel_theme": ("auto", "dark", "light", "system"),
    "panel_sort": ("name", "state"),
    "log_level": ("debug", "info", "warning"),
}
_STR_LISTS = ("roots", "repos", "ignore", "exclude_dirs")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _str_list(v: Any) -> tuple[str, ...] | None:
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return tuple(v)
    return None


def _validate_color(v: Any, allowed: tuple[str, ...]) -> bool:
    return isinstance(v, str) and (v in allowed or bool(HEX_RE.fullmatch(v)))


def from_dict(data: dict[str, Any]) -> tuple[Config, list[str]]:
    """Build a Config from parsed TOML. Invalid values fall back to defaults with a warning."""
    warnings: list[str] = []
    defaults = Config()
    values: dict[str, Any] = {}
    known = {f.name for f in fields(Config)}
    for key, v in data.items():
        if key not in known:
            warnings.append(f"unknown key '{key}' ignored")
            continue
        if key in _INT_RANGES:
            lo, hi = _INT_RANGES[key]
            if not _is_int(v) or v < lo or (hi is not None and v > hi):
                rng = f"{lo}–{hi}" if hi is not None else f"≥ {lo}"
                warnings.append(f"'{key}' must be an integer {rng}; using {getattr(defaults, key)}")
                continue
            values[key] = v
        elif key in _BOOLS:
            if not isinstance(v, bool):
                warnings.append(f"'{key}' must be true or false; using {getattr(defaults, key)}")
                continue
            values[key] = v
        elif key in _STR_CHOICES:
            choices = _STR_CHOICES[key]
            if not isinstance(v, str) or (choices and v not in choices):
                allowed = ", ".join(choices) if choices else "a string"
                warnings.append(f"'{key}' must be {allowed}; using '{getattr(defaults, key)}'")
                continue
            values[key] = v
        elif key in _STR_LISTS:
            lst = _str_list(v)
            if lst is None:
                warnings.append(f"'{key}' must be a list of strings; using the default")
                continue
            values[key] = lst
        elif key == "indicator":
            ind, w = _indicator(v)
            values[key] = ind
            warnings += w
        elif key == "repo":
            rep, w = _repo_overrides(v)
            values[key] = rep
            warnings += w
    for key in ("terminal", "file_manager", "editor"):
        tmpl = values.get(key, "")
        if tmpl and "{path}" not in tmpl:
            warnings.append(f"'{key}' has no {{path}} placeholder; the path is passed as cwd only")
    return replace(defaults, **values), warnings


def _indicator(v: Any) -> tuple[IndicatorConfig, list[str]]:
    d = IndicatorConfig()
    if not isinstance(v, dict):
        return d, ["[indicator] must be a table; using defaults"]
    warnings: list[str] = []
    vals: dict[str, Any] = {}
    known = {f.name for f in fields(IndicatorConfig)}
    for key, x in v.items():
        if key not in known:
            warnings.append(f"unknown key 'indicator.{key}' ignored")
        elif key in ("label", "top_dot", "bottom_dot", "tint"):
            lst = _str_list(x)
            if lst is None or any(t not in TRIGGERS for t in lst):
                warnings.append(
                    f"'indicator.{key}' must be a list drawn from push, pull, dirty; using default"
                )
                continue
            vals[key] = tuple(dict.fromkeys(lst))
        elif key in ("top_dot_color", "bottom_dot_color"):
            if not _validate_color(x, SYMBOLIC_COLORS):
                warnings.append(
                    f"'indicator.{key}' must be foreground, warning, error, success or #rrggbb; "
                    f"using '{getattr(d, key)}'"
                )
                continue
            vals[key] = x
        elif key == "tint_color":
            if not _validate_color(x, TINT_COLORS):
                warnings.append(
                    "'indicator.tint_color' must be warning, error, success or #rrggbb; "
                    f"using '{d.tint_color}'"
                )
                continue
            vals[key] = x
        elif key == "marker":
            if x not in MARKERS:
                warnings.append(f"'indicator.marker' must be arrow or dot; using '{d.marker}'")
                continue
            vals[key] = x
        elif key == "glyph_color":
            if not (isinstance(x, str) and HEX_RE.fullmatch(x)):
                warnings.append(f"'indicator.glyph_color' must be #rrggbb; using '{d.glyph_color}'")
                continue
            vals[key] = x
    return replace(d, **vals), warnings


def _repo_overrides(v: Any) -> tuple[dict[str, RepoOverride], list[str]]:
    if not isinstance(v, dict):
        return {}, ["[repo] must be a table of tables; ignored"]
    out: dict[str, RepoOverride] = {}
    warnings: list[str] = []
    for path, tbl in v.items():
        if not isinstance(tbl, dict):
            warnings.append(f'[repo."{path}"] must be a table; ignored')
            continue
        ov = RepoOverride()
        for key, x in tbl.items():
            if key == "fetch":
                if isinstance(x, bool):
                    ov = replace(ov, fetch=x)
                else:
                    warnings.append(f'[repo."{path}"] fetch must be true or false')
            elif key == "name":
                if isinstance(x, str) and x.strip():
                    ov = replace(ov, name=x.strip())
                else:
                    warnings.append(f'[repo."{path}"] name must be a non-empty string')
            else:
                warnings.append(f"unknown key '{key}' in [repo.\"{path}\"] ignored")
        out[path] = ov
    return out, warnings


class ConfigError(Exception):
    """The file exists but is not valid TOML."""


def default_text() -> str:
    return resources.files("repotray").joinpath("default_config.toml").read_text("utf-8")


def load(path: Path) -> tuple[Config, list[str]]:
    """Load a config file. Missing file → defaults. Raises ConfigError for invalid TOML."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Config(), []
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return from_dict(data)


def ensure_exists(path: Path) -> bool:
    """Write the commented default config if there is none. Returns True when written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_text(), "utf-8")
    return True


class ConfigWatcher:
    """Holds the current Config and reloads it when the file's mtime changes."""

    def __init__(self, path: Path, initial: Config | None = None) -> None:
        self.path = path
        self.config = initial or Config()
        self.warnings: list[str] = []
        self.error: str | None = None
        self._stamp: tuple[float, int] | None = None

    def _stat(self) -> tuple[float, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_mtime, st.st_size)

    def load(self) -> Config:
        self._stamp = self._stat()
        try:
            self.config, self.warnings = load(self.path)
            self.error = None
        except ConfigError as exc:
            self.error = str(exc)
        return self.config

    def poll(self) -> bool:
        """Reload when the file changed. True if a new Config (or error) resulted."""
        stamp = self._stat()
        if stamp == self._stamp:
            return False
        before = (self.config, self.error)
        self.load()
        return (self.config, self.error) != before

    @property
    def warning_text(self) -> str | None:
        if self.error:
            return f"Config error, using previous settings: {self.error.splitlines()[0]}"
        if self.warnings:
            more = f" (+{len(self.warnings) - 1} more)" if len(self.warnings) > 1 else ""
            return f"Config: {self.warnings[0]}{more}"
        return None
