"""Backend registry: selection order and third-party entry points."""

import importlib.metadata as md
import sys
import types

import pytest

from repotray.backends import registry
from repotray.backends.base import ProbeResult


class DummyBackend:
    name = "dummy"

    @classmethod
    def probe(cls, platform):
        return ProbeResult(999, "dummy plugin")


@pytest.fixture
def plugin(monkeypatch):
    mod = types.ModuleType("repotray_dummy_plugin")
    mod.DummyBackend = DummyBackend
    monkeypatch.setitem(sys.modules, "repotray_dummy_plugin", mod)
    ep = md.EntryPoint(
        name="dummy", value="repotray_dummy_plugin:DummyBackend", group=registry.ENTRY_POINT_GROUP
    )
    real = registry.entry_points

    def fake_entry_points(group=None, **kw):
        if group == registry.ENTRY_POINT_GROUP:
            return [ep]
        return real(group=group, **kw)

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)
    return ep


def test_entry_point_plugin_is_listed_and_wins_on_score(plugin):
    assert "dummy" in registry.available()
    name, cls = registry.select(platform=None)
    assert name == "dummy" and cls is DummyBackend


def test_explicit_choice_order(plugin, monkeypatch):
    monkeypatch.setenv("REPOTRAY_BACKEND", "fake")
    assert registry.select(None, "dummy", None)[0] == "fake"  # env beats config
    assert registry.select(None, "dummy", "dummy")[0] == "dummy"  # CLI beats env
    monkeypatch.delenv("REPOTRAY_BACKEND")
    assert registry.select(None, "fake", None)[0] == "fake"


def test_unknown_backend():
    with pytest.raises(registry.BackendError):
        registry.load("nope")


def test_fake_never_auto_selected():
    res = registry.probe("fake", None)
    assert res.score == 0 and "never auto-selected" in res.reason


def test_import_errors_become_zero_scores(monkeypatch):
    monkeypatch.setitem(registry.BUILTINS, "broken", "repotray.no_such_module:X")
    res = registry.probe("broken", None)
    assert res.score == 0 and "ModuleNotFoundError" in res.reason


def test_builtins_cannot_be_shadowed(monkeypatch):
    ep = md.EntryPoint(name="xapp", value="os:getcwd", group=registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(registry, "entry_points", lambda group=None, **kw: [ep])
    assert registry.available()["xapp"] == registry.BUILTINS["xapp"]
