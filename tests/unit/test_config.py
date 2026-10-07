import os
import time
import tomllib

import pytest

from repotray.core import config as c
from repotray.core.config import Config, ConfigError, ConfigWatcher, from_dict, load


def test_defaults_match_default_file():
    data = tomllib.loads(c.default_text())
    cfg, warnings = from_dict(data)
    assert warnings == []
    assert cfg == Config()


def test_missing_file_gives_defaults(tmp_path):
    cfg, warnings = load(tmp_path / "none.toml")
    assert cfg == Config() and warnings == []


def test_ensure_exists(tmp_path):
    p = tmp_path / "sub/config.toml"
    assert c.ensure_exists(p)
    assert not c.ensure_exists(p)
    assert load(p)[0] == Config()


@pytest.mark.parametrize(
    ("key", "bad", "good"),
    [
        ("max_depth", 13, 12),
        ("max_depth", -1, 0),
        ("status_interval", 9, 10),
        ("fetch_interval", 59, 60),
        ("rescan_interval", 10, 60),
        ("workers", 0, 32),
        ("fetch_workers", 33, 1),
        ("fetch_timeout", 4, 600),
        ("action_timeout", 1801, 10),
        ("max_depth", True, 3),
        ("max_depth", "4", 4),
    ],
)
def test_int_ranges(key, bad, good):
    cfg, warnings = from_dict({key: bad})
    assert getattr(cfg, key) == getattr(Config(), key)
    assert len(warnings) == 1 and key in warnings[0]
    cfg, warnings = from_dict({key: good})
    assert getattr(cfg, key) == good and warnings == []


@pytest.mark.parametrize(
    "key",
    [
        "descend_into_repos",
        "count_untracked_as_dirty",
        "count_no_upstream_as_push",
        "notifications",
    ],
)
def test_bools(key):
    cfg, warnings = from_dict({key: "yes"})
    assert getattr(cfg, key) == getattr(Config(), key) and warnings
    cfg, warnings = from_dict({key: not getattr(Config(), key)})
    assert getattr(cfg, key) != getattr(Config(), key) and not warnings


@pytest.mark.parametrize(
    ("key", "bad", "good"),
    [
        ("sync_strategy", "squash", "merge"),
        ("panel_theme", "blue", "dark"),
        ("log_level", "trace", "debug"),
        ("backend", 3, "pystray"),
        ("terminal", ["x"], "kitty --directory {path}"),
    ],
)
def test_strings(key, bad, good):
    cfg, warnings = from_dict({key: bad})
    assert getattr(cfg, key) == getattr(Config(), key) and warnings
    cfg, warnings = from_dict({key: good})
    assert getattr(cfg, key) == good and not warnings


def test_template_without_placeholder_warns_but_is_kept():
    cfg, warnings = from_dict({"terminal": "xterm"})
    assert cfg.terminal == "xterm" and "placeholder" in warnings[0]


def test_lists():
    cfg, warnings = from_dict({"roots": "~/code"})
    assert cfg.roots == ("~",) and warnings
    cfg, warnings = from_dict({"roots": ["~/a", "~/b"], "ignore": [], "exclude_dirs": ["x"]})
    assert cfg.roots == ("~/a", "~/b") and cfg.exclude_dirs == ("x",) and not warnings


def test_unknown_keys():
    cfg, warnings = from_dict({"rootz": [], "indicator": {"lable": []}, "repo": {"/x": {"y": 1}}})
    assert len(warnings) == 3
    assert cfg.indicator == c.IndicatorConfig()


def test_indicator_validation():
    cfg, w = from_dict(
        {
            "indicator": {
                "label": ["dirty", "push", "dirty"],
                "top_dot": ["nope"],
                "top_dot_color": "#12abef",
                "bottom_dot_color": "purple",
                "tint": ["push"],
                "tint_color": "foreground",
                "glyph_color": "#fff",
            }
        }
    )
    ind = cfg.indicator
    assert ind.label == ("dirty", "push")
    assert ind.top_dot == ("push",)
    assert ind.top_dot_color == "#12abef"
    assert ind.bottom_dot_color == "warning"
    assert ind.tint == ("push",)
    assert ind.tint_color == "warning"
    assert ind.glyph_color == "#e1e1e1"
    assert len(w) == 4


def test_repo_overrides(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    cfg, w = from_dict({"repo": {str(repo): {"fetch": False, "name": " mono "}, "~/x": 3}})
    assert len(w) == 1
    ov = cfg.override_for(repo.resolve())
    assert ov is not None and ov.fetch is False and ov.name == "mono"


def test_parse_error_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("roots = [\n")
    with pytest.raises(ConfigError):
        load(p)


def test_watcher_reload_and_keep_previous_on_error(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("max_depth = 2\n")
    w = ConfigWatcher(p)
    assert w.load().max_depth == 2
    assert not w.poll()
    p.write_text("max_depth = 3\n")
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert w.poll() and w.config.max_depth == 3
    p.write_text("max_depth = [\n")
    os.utime(p, (time.time() + 10, time.time() + 10))
    assert w.poll()
    assert w.config.max_depth == 3
    assert w.error and w.warning_text.startswith("Config error")
    p.write_text("max_depth = 5\nbogus = 1\n")
    os.utime(p, (time.time() + 15, time.time() + 15))
    assert w.poll() and w.config.max_depth == 5 and w.error is None
    assert "bogus" in w.warning_text


def test_scan_key_changes():
    a = Config()
    assert a.scan_key() == Config(status_interval=30).scan_key()
    assert a.scan_key() != Config(max_depth=2).scan_key()
