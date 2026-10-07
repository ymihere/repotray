"""Shared fixtures. Every test runs with an isolated git config and XDG directories."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# Qt tests run on Qt's offscreen platform (no display needed) unless a real desktop is asked for.
# Set before any test module creates a QApplication.
if os.environ.get("REPOTRAY_GUI_TESTS") != "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("env")
    gitconfig = base / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Test User\n\temail = test@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n"
        "[commit]\n\tgpgsign = false\n"
        "[tag]\n\tgpgsign = false\n"
        "[advice]\n\tdetachedHead = false\n"
        '[protocol "file"]\n\tallow = always\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        d = base / var.lower()
        d.mkdir()
        monkeypatch.setenv(var, str(d))
    rt = base / "runtime"
    rt.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    for var in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "REPOTRAY_BACKEND",
        "REPOTRAY_CONFIG",
    ):
        monkeypatch.delenv(var, raising=False)
    from repotray.platform import current

    current.cache_clear()
    yield base
    current.cache_clear()


def git(cwd: Path, *args: str, check: bool = True, input: str | None = None) -> str:
    cp = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
        input=input,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true"},
    )
    if check and cp.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{cp.stdout}\n{cp.stderr}")
    return cp.stdout


def commit(repo: Path, name: str = "file.txt", content: str | None = None, msg: str = "") -> str:
    f = repo / name
    f.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        prev = f.read_text() if f.exists() else ""
        content = prev + "line\n"
    f.write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg or f"change {name}")
    return git(repo, "rev-parse", "HEAD").strip()


@dataclass
class Fixture:
    root: Path
    remote: Path

    def clone(self, name: str) -> Path:
        dest = self.root / name
        subprocess.run(
            ["git", "clone", "-q", str(self.remote), str(dest)], check=True, capture_output=True
        )
        return dest


@pytest.fixture
def remote_fixture(tmp_path) -> Fixture:
    """A bare remote with one commit on main, and a place to clone it."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", str(seed))
    commit(seed, "README", "hello\n", "initial")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-q", "origin", "main")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    root = tmp_path / "work"
    root.mkdir()
    return Fixture(root=root, remote=remote)


def snapshot_tree(repo: Path) -> dict:
    """HEAD, index status and file contents — to prove a repo was left untouched."""
    files = {}
    for p in sorted(repo.rglob("*")):
        if ".git" in p.relative_to(repo).parts or not p.is_file():
            continue
        files[str(p.relative_to(repo))] = p.read_bytes()
    return {
        "head": git(repo, "rev-parse", "HEAD").strip(),
        "status": git(repo, "status", "--porcelain=v2", "--branch"),
        "files": files,
        "branch": git(repo, "symbolic-ref", "-q", "HEAD", check=False).strip(),
    }
