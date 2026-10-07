"""Discovery of git repositories below the configured roots."""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repotray.core.config import Config, expand
from repotray.core.gitrun import CallKind, Runner
from repotray.core.types import RepoInfo

log = logging.getLogger(__name__)


def is_repo(path: Path) -> bool:
    try:
        return os.path.lexists(path / ".git")
    except OSError:
        return False


def walk_root(root: Path, max_depth: int, exclude: frozenset[str], descend: bool) -> Iterable[Path]:
    """Yield repository directories below ``root`` (the root itself is depth 0)."""
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        found = is_repo(current)
        if found:
            yield current
            if not descend:
                continue
        if depth >= max_depth:
            continue
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:  # PermissionError, vanished, not a directory
            continue
        children = []
        for e in entries:
            name = e.name
            if name.startswith(".") or name in exclude:
                continue
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            children.append(Path(e.path))
        children.sort(reverse=True)
        stack.extend((c, depth + 1) for c in children)


def _abbrev(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home)) if path != home else "~"
    except ValueError:
        return str(path)


def display_names(paths: list[Path], overrides: dict[Path, str]) -> dict[Path, str]:
    """basename; parent/basename on collision; then the ~-abbreviated path."""
    names: dict[Path, str] = {}
    by_base: dict[str, list[Path]] = {}
    for p in paths:
        if p in overrides:
            continue
        by_base.setdefault(p.name, []).append(p)
    for base, group in by_base.items():
        if len(group) == 1:
            names[group[0]] = base
            continue
        by_parent: dict[str, list[Path]] = {}
        for p in group:
            by_parent.setdefault(f"{p.parent.name}/{p.name}", []).append(p)
        for label, sub in by_parent.items():
            if len(sub) == 1:
                names[sub[0]] = label
            else:
                for p in sub:
                    names[p] = _abbrev(p)
    names.update({p: n for p, n in overrides.items() if p in set(paths)})
    return names


def find_repo_paths(config: Config) -> tuple[list[Path], list[str]]:
    """Walk roots and explicit repos, apply ignore globs, dedupe. No git calls."""
    warnings: list[str] = []
    exclude = frozenset(config.exclude_dirs)
    seen: dict[Path, None] = {}
    for root_s in config.roots:
        root = expand(root_s)
        if not root.is_dir():
            warnings.append(f"root {root_s} does not exist")
            continue
        root = root.resolve()
        for p in walk_root(root, config.max_depth, exclude, config.descend_into_repos):
            seen.setdefault(p.resolve(), None)
    for repo_s in config.repos:
        p = expand(repo_s)
        if p.is_dir() and is_repo(p):
            seen.setdefault(p.resolve(), None)
        else:
            warnings.append(f"repos entry {repo_s} is not a git repository")
    globs = [str(expand(g)) for g in config.ignore]
    paths = [p for p in seen if not any(fnmatch.fnmatch(str(p), g) for g in globs)]
    return paths, warnings


def scan(config: Config, runner: Runner, workers: int = 8) -> tuple[list[RepoInfo], list[str]]:
    paths, warnings = find_repo_paths(config)

    def git_dir(p: Path) -> Path | None:
        res = runner(["rev-parse", "--absolute-git-dir"], p, 15.0, kind=CallKind.QUERY)
        if not res.ok:
            return None
        out = res.out.strip()
        return Path(out) if out else None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        dirs = list(pool.map(git_dir, paths))
    valid: list[tuple[Path, Path]] = []
    for p, d in zip(paths, dirs, strict=True):
        if d is None:
            log.warning("dropping %s: not a usable git repository", p)
            continue
        # Bare repositories have no work tree; `.git` dirs only exist in non-bare ones, but a
        # `.git` file could point anywhere. Require the git dir to differ from the work tree.
        if d == p:
            continue
        valid.append((p, d))
    overrides_name: dict[Path, str] = {}
    fetch_off: set[Path] = set()
    for p, _ in valid:
        ov = config.override_for(p)
        if ov:
            if ov.name:
                overrides_name[p] = ov.name
            if not ov.fetch:
                fetch_off.add(p)
    names = display_names([p for p, _ in valid], overrides_name)
    infos = [
        RepoInfo(path=p, git_dir=d, name=names[p], fetch_enabled=p not in fetch_off)
        for p, d in valid
    ]
    infos.sort(key=lambda r: (r.name.casefold(), str(r.path)))
    return infos, warnings
