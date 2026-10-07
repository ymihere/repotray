"""Tray icon names, full-colour SVGs and rasters, all derived from the committed icon data."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path


def data_dir() -> Path:
    return Path(str(resources.files("repotray").joinpath("icons/data")))


def symbolic_dir() -> Path:
    return data_dir() / "symbolic"


@cache
def geometry() -> dict:
    return json.loads((data_dir() / "geometry.json").read_text("utf-8"))
