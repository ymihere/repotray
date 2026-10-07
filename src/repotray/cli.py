"""Command line interface."""

from __future__ import annotations

import argparse

from repotray import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="repotray")
    p.add_argument("--version", action="version", version=__version__)
    return p


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
