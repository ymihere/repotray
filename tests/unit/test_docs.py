"""Docs stay in sync with the code: config keys, CLI commands, relative links."""

import re
from dataclasses import fields
from pathlib import Path

import pytest

from repotray.cli import build_parser
from repotray.core.config import Config, IndicatorConfig, RepoOverride

ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text("utf-8")


def config_keys() -> list[str]:
    keys = [f.name for f in fields(Config) if f.name not in ("indicator", "repo")]
    keys += [f"[indicator] {f.name}" for f in fields(IndicatorConfig)]
    keys += [f'[repo."<path>"] {f.name}' for f in fields(RepoOverride)]
    return keys


def test_every_config_key_documented():
    doc = read("docs/configuration.md")
    for key in config_keys():
        name = key.split()[-1]
        assert f"`{name}`" in doc or f"`{key}`" in doc, f"{key} missing in docs/configuration.md"
    for f in fields(IndicatorConfig):
        assert f"`{f.name}`" in doc


def test_every_config_key_in_default_file():
    text = read("src/repotray/default_config.toml")
    for f in fields(Config):
        if f.name not in ("indicator", "repo"):
            assert re.search(rf"^{f.name} =", text, re.M), f.name
    for f in fields(IndicatorConfig):
        assert re.search(rf"^{f.name} =", text, re.M), f.name


def commands() -> list[str]:
    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    return list(sub.choices)


@pytest.mark.parametrize("doc", ["README.md", "docs/cli.md"])
def test_every_cli_command_documented(doc):
    text = read(doc)
    for cmd in commands():
        assert re.search(rf"repotray(?: \[tray\])? {cmd}\b|repotray \[{cmd}\]", text), (
            f"`repotray {cmd}` missing in {doc}"
        )


LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def markdown_files() -> list[Path]:
    files = [p for p in ROOT.glob("*.md")] + list((ROOT / "docs").glob("*.md"))
    files += list((ROOT / ".github").rglob("*.md"))
    return [p for p in files if p.name not in ("CLAUDE.local.md", "HANDOFF.md")]


@pytest.mark.parametrize("md", markdown_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(md):
    text = md.read_text("utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # code blocks are examples
    for target in LINK.findall(text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#")[0]
        assert (md.parent / path).exists(), f"{md.name}: broken link {target}"
