import os
import sys
from pathlib import Path

import pytest

from repotray.core.config import Config, RepoOverride
from repotray.core.gitrun import GitResult
from repotray.core.scanner import display_names, find_repo_paths, scan


def mkrepo(path: Path, kind: str = "dir") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if kind == "dir":
        (path / ".git").mkdir()
    else:  # worktree / submodule style
        (path / ".git").write_text("gitdir: /somewhere/else\n")
    return path


def cfg(root: Path, **kw) -> Config:
    return Config(roots=(str(root),), **kw)


def found(config: Config) -> set[str]:
    paths, _ = find_repo_paths(config)
    root = Path(config.roots[0]).resolve() if config.roots else Path("/")
    return {p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p) for p in paths}


def test_depth_limit(tmp_path):
    mkrepo(tmp_path / "a")
    mkrepo(tmp_path / "x/y/b")
    mkrepo(tmp_path / "x/y/z/deep")
    assert found(cfg(tmp_path, max_depth=3)) == {"a", "x/y/b"}
    assert found(cfg(tmp_path, max_depth=4)) == {"a", "x/y/b", "x/y/z/deep"}
    assert found(cfg(tmp_path, max_depth=1)) == {"a"}


def test_root_itself_is_a_repo(tmp_path):
    mkrepo(tmp_path / "r")
    assert found(cfg(tmp_path / "r", max_depth=0)) == {"."}


def test_exclusions_and_hidden(tmp_path):
    mkrepo(tmp_path / "node_modules/pkg")
    mkrepo(tmp_path / ".hidden/repo")
    mkrepo(tmp_path / "keep")
    mkrepo(tmp_path / "custom/repo")
    assert found(cfg(tmp_path)) == {"keep", "custom/repo"}
    assert found(cfg(tmp_path, exclude_dirs=("custom",))) == {"keep", "node_modules/pkg"}


def test_hidden_root_and_hidden_repos_entry_are_scanned(tmp_path):
    hidden_root = tmp_path / ".config"
    mkrepo(hidden_root / "nvim")
    hidden_repo = mkrepo(tmp_path / "elsewhere/.dotfiles")
    c = Config(roots=(str(hidden_root),), repos=(str(hidden_repo),))
    paths, warnings = find_repo_paths(c)
    assert set(paths) == {(hidden_root / "nvim").resolve(), hidden_repo.resolve()}
    assert warnings == []


def test_nested_repos(tmp_path):
    mkrepo(tmp_path / "outer")
    mkrepo(tmp_path / "outer/libs/inner")
    assert found(cfg(tmp_path)) == {"outer"}
    assert found(cfg(tmp_path, descend_into_repos=True)) == {"outer", "outer/libs/inner"}


def test_git_file_worktree(tmp_path):
    mkrepo(tmp_path / "wt", kind="file")
    assert found(cfg(tmp_path)) == {"wt"}


def test_bare_repo_ignored(tmp_path):
    bare = tmp_path / "bare.git"
    bare.mkdir()
    (bare / "HEAD").write_text("ref: refs/heads/main\n")
    (bare / "objects").mkdir()
    (bare / "refs").mkdir()
    assert found(cfg(tmp_path)) == set()


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="symlinks/permissions")


@posix_only
def test_symlink_loop_and_symlinked_dirs_not_followed(tmp_path):
    mkrepo(tmp_path / "real/repo")
    os.symlink(tmp_path, tmp_path / "real/loop")
    os.symlink(tmp_path / "real", tmp_path / "alias")
    assert found(cfg(tmp_path, max_depth=12)) == {"real/repo"}


@posix_only
def test_symlinked_root_is_followed(tmp_path):
    mkrepo(tmp_path / "target/repo")
    os.symlink(tmp_path / "target", tmp_path / "link")
    paths, _ = find_repo_paths(Config(roots=(str(tmp_path / "link"),)))
    assert paths == [(tmp_path / "target/repo").resolve()]


def test_ignore_globs(tmp_path):
    mkrepo(tmp_path / "archive/old1")
    mkrepo(tmp_path / "archive/old2")
    mkrepo(tmp_path / "live")
    assert found(cfg(tmp_path, ignore=(str(tmp_path / "archive/*"),))) == {"live"}


def test_missing_root_and_bad_repos_entry_warn(tmp_path):
    c = Config(roots=(str(tmp_path / "nope"),), repos=(str(tmp_path),))
    paths, warnings = find_repo_paths(c)
    assert paths == []
    assert len(warnings) == 2


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions as non-root",
)
def test_permission_error_ignored(tmp_path):
    mkrepo(tmp_path / "ok")
    locked = tmp_path / "locked"
    mkrepo(locked / "inside")
    locked.chmod(0)
    try:
        assert "ok" in found(cfg(tmp_path))
    finally:
        locked.chmod(0o755)


def test_display_names_collisions():
    a = Path("/x/work/api")
    b = Path("/x/home/api")
    c = Path("/x/one/same/tool")
    d = Path("/x/two/same/tool")
    e = Path("/x/solo")
    names = display_names([a, b, c, d, e], {})
    assert names[a] == "work/api" and names[b] == "home/api"
    assert names[c] == str(c) and names[d] == str(d)
    assert names[e] == "solo"
    assert display_names([a, e], {a: "API"})[a] == "API"


class RevParse:
    def __call__(self, args, cwd, timeout, *, kind):
        if Path(cwd).name == "broken":
            return GitResult(128, b"", b"fatal: bad", False, ())
        return GitResult(0, f"{cwd}/.git\n".encode(), b"", False, ())


def test_scan_builds_infos_with_overrides(tmp_path):
    mkrepo(tmp_path / "b-repo")
    mkrepo(tmp_path / "A-repo")
    mkrepo(tmp_path / "broken")
    key = str(tmp_path / "b-repo")
    c = Config(roots=(str(tmp_path),), repo={key: RepoOverride(fetch=False, name="bee")})
    infos, _ = scan(c, RevParse())
    assert [i.name for i in infos] == ["A-repo", "bee"]
    bee = infos[1]
    assert not bee.fetch_enabled
    assert bee.git_dir == (tmp_path / "b-repo/.git").resolve()


def test_scan_performance(tmp_path):
    for i in range(60):
        mkrepo(tmp_path / f"group{i % 6}/sub/repo{i}")
        (tmp_path / f"group{i % 6}/sub/repo{i}/src/a/b").mkdir(parents=True)
    import time

    t = time.monotonic()
    infos, _ = scan(cfg(tmp_path), RevParse())
    assert len(infos) == 60
    assert time.monotonic() - t < 2
