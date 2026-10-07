"""Real git in tmp_path: status, push, pull, sync, conflict abort, timeouts, no prompting."""

from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import commit, git, snapshot_tree
from repotray.core.actions import ActionContext, run_action
from repotray.core.config import Config
from repotray.core.gitrun import GitRunner
from repotray.core.gitstatus import check_status, fetch_repo
from repotray.core.scanner import scan
from repotray.core.types import ActionKind

pytestmark = [
    pytest.mark.integration,
    # Hooks, chmod and TCP fixtures assume POSIX; Windows coverage is unit tests only for now.
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only fixtures"),
]


def info_for(path: Path):
    infos, _ = scan(Config(roots=(), repos=(str(path),)), GitRunner())
    assert len(infos) == 1
    return infos[0]


def status(path: Path):
    return check_status(GitRunner(), info_for(path))


def act(kind, path, **kw):
    ctx = ActionContext(runner=GitRunner(), **kw)
    return run_action(ctx, kind, info_for(path))


@pytest.fixture
def pair(remote_fixture):
    """Two clones of the same remote: `mine` (under test) and `theirs` (pushes upstream work)."""
    mine = remote_fixture.clone("mine")
    theirs = remote_fixture.clone("theirs")
    return remote_fixture, mine, theirs


def make_behind(theirs: Path, mine: Path, n=1, name="theirs.txt"):
    git(theirs, "pull", "-q", "--ff-only")
    for _ in range(n):
        commit(theirs, name)
    git(theirs, "push", "-q")
    git(mine, "fetch", "-q")


def test_status_states(pair):
    _, mine, theirs = pair
    s = status(mine)
    assert (s.branch, s.upstream, s.ahead, s.behind) == ("main", "origin/main", 0, 0)
    assert s.upstream_remote == "origin" and s.upstream_merge == "refs/heads/main"
    commit(mine, "a.txt")
    commit(mine, "a.txt")
    assert status(mine).ahead == 2 and status(mine).pushable
    make_behind(theirs, mine, 3)
    s = status(mine)
    assert (s.ahead, s.behind) == (2, 3) and s.diverged
    (mine / "untracked").write_text("x")
    (mine / "README").write_text("changed\n")
    s = status(mine)
    assert s.untracked == 1 and s.unstaged == 1 and s.tracked_changes


def test_status_never_writes_index(pair):
    _, mine, _ = pair
    (mine / "README").write_text("changed\n")
    index = mine / ".git/index"
    before = index.stat().st_mtime_ns
    os.utime(mine / "README", None)
    status(mine)
    assert index.stat().st_mtime_ns == before
    assert not (mine / ".git/index.lock").exists()


def test_detached_and_no_upstream(pair):
    _, mine, _ = pair
    git(mine, "checkout", "-q", "--detach")
    assert status(mine).detached
    git(mine, "checkout", "-q", "-b", "local-only")
    s = status(mine)
    assert s.no_upstream and not s.pushable


def test_upstream_gone(pair):
    rf, mine, theirs = pair
    git(theirs, "push", "-q", "origin", "main:feature")
    git(mine, "fetch", "-q")
    git(mine, "checkout", "-q", "-b", "feature", "--track", "origin/feature")
    git(theirs, "push", "-q", "origin", ":feature")
    git(mine, "fetch", "-q", "--prune")
    s = status(mine)
    assert s.upstream_gone and s.no_upstream


def test_push_clears_ahead(pair):
    rf, mine, _ = pair
    commit(mine, "a.txt")
    res = act(ActionKind.PUSH, mine)
    assert res.ok, res.stderr
    assert res.message == "Pushed 1 commit to origin/main"
    assert status(mine).ahead == 0
    assert git(rf.remote, "rev-parse", "main") == git(mine, "rev-parse", "HEAD")


def test_push_uses_upstream_branch_name(pair):
    rf, mine, theirs = pair
    git(theirs, "push", "-q", "origin", "main:other")
    git(mine, "fetch", "-q")
    git(mine, "checkout", "-q", "-b", "local-name", "--track", "origin/other")
    commit(mine, "b.txt")
    res = act(ActionKind.PUSH, mine)
    assert res.ok, res.stderr
    assert git(rf.remote, "rev-parse", "other") == git(mine, "rev-parse", "HEAD")
    assert git(rf.remote, "branch", "--list", "local-name") == ""


def test_pull_clears_behind(pair):
    _, mine, theirs = pair
    make_behind(theirs, mine, 2)
    res = act(ActionKind.PULL, mine)
    assert res.ok, res.stderr
    assert status(mine).behind == 0


def test_pull_refused_when_diverged_without_running_pull(pair):
    _, mine, theirs = pair
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    res = act(ActionKind.PULL, mine)
    assert not res.ok and res.message == "Diverged — use Sync"


def test_sync_rebases_and_pushes(pair):
    rf, mine, theirs = pair
    commit(mine, "mine.txt")
    make_behind(theirs, mine, 2)
    res = act(ActionKind.SYNC, mine)
    assert res.ok, res.stderr
    s = status(mine)
    assert (s.ahead, s.behind) == (0, 0)
    # Rebased: linear history, no merge commit.
    assert git(mine, "rev-list", "--merges", "--count", "HEAD").strip() == "0"
    assert git(rf.remote, "rev-parse", "main") == git(mine, "rev-parse", "HEAD")


def test_sync_conflict_aborts_and_restores(pair):
    _, mine, theirs = pair
    commit(mine, "README", "mine\n")
    commit(theirs, "README", "theirs\n")
    git(theirs, "push", "-q")
    git(mine, "fetch", "-q")
    (mine / "untracked.txt").write_text("keep me\n")
    before = snapshot_tree(mine)
    res = act(ActionKind.SYNC, mine)
    assert not res.ok
    assert res.restored is True
    assert "conflict" in res.message.lower()
    assert snapshot_tree(mine) == before
    assert not (mine / ".git/rebase-merge").exists() and not (mine / ".git/rebase-apply").exists()


def test_sync_conflict_merge_strategy_restores(pair):
    _, mine, theirs = pair
    commit(mine, "README", "mine\n")
    commit(theirs, "README", "theirs\n")
    git(theirs, "push", "-q")
    git(mine, "fetch", "-q")
    before = snapshot_tree(mine)
    res = act(ActionKind.SYNC, mine, sync_strategy="merge")
    assert not res.ok and res.restored is True
    assert snapshot_tree(mine) == before
    assert not (mine / ".git/MERGE_HEAD").exists()


def test_sync_refused_with_tracked_changes(pair):
    _, mine, theirs = pair
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    (mine / "a.txt").write_text("dirty\n")
    before = snapshot_tree(mine)
    res = act(ActionKind.SYNC, mine)
    assert not res.ok and res.message == "Commit or stash first"
    assert res.command == ()
    assert snapshot_tree(mine) == before


def test_sync_with_untracked_only_proceeds(pair):
    _, mine, theirs = pair
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    (mine / "scratch.txt").write_text("x")
    res = act(ActionKind.SYNC, mine)
    assert res.ok, res.stderr
    assert (mine / "scratch.txt").read_text() == "x"


def test_merge_strategy_creates_merge_commit_without_editor(pair):
    _, mine, theirs = pair
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    res = act(ActionKind.SYNC, mine, sync_strategy="merge")
    assert res.ok, res.stderr
    assert git(mine, "rev-list", "--merges", "--count", "HEAD").strip() == "1"
    assert status(mine).ahead == 0


def test_sync_push_rejected_keeps_local_rebase(pair, tmp_path):
    rf, mine, theirs = pair
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    hook = rf.remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\necho 'denied by policy' >&2\nexit 1\n")
    hook.chmod(0o755)
    res = act(ActionKind.SYNC, mine)
    assert not res.ok
    assert res.message.startswith("rebased locally, push rejected")
    s = status(mine)
    assert s.behind == 0 and s.ahead == 1


# --- network failure modes ----------------------------------------------------------------------


class SilentServer:
    """Accepts TCP connections and never answers."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.conns = []
        self.stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stop:
            try:
                c, _ = self.sock.accept()
                self.conns.append(c)
            except OSError:
                return

    def close(self):
        self.stop = True
        for c in self.conns:
            c.close()
        self.sock.close()


def test_action_timeout_kills_and_leaves_repo_unchanged(pair):
    _, mine, _ = pair
    commit(mine, "a.txt")
    server = SilentServer()
    try:
        git(mine, "remote", "set-url", "origin", f"http://127.0.0.1:{server.port}/x.git")
        before = snapshot_tree(mine)
        t = time.monotonic()
        res = act(ActionKind.PUSH, mine, timeout=3)
        elapsed = time.monotonic() - t
    finally:
        server.close()
    assert not res.ok and "timed out" in res.message
    assert elapsed < 6
    assert snapshot_tree(mine) == before


class AuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="test"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET  # noqa: N815

    def log_message(self, *a):
        pass


def test_fetch_needing_credentials_fails_fast(pair):
    _, mine, _ = pair
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/private.git"
        git(mine, "remote", "set-url", "origin", url)
        t = time.monotonic()
        res = fetch_repo(GitRunner(), mine, 30)
        elapsed = time.monotonic() - t
    finally:
        server.shutdown()
    assert not res.ok and not res.timed_out
    assert elapsed < 10
    assert "Authentication failed" in res.err or "could not read Username" in res.err


def test_ssh_closed_port_fails_fast(pair):
    _, mine, _ = pair
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    git(mine, "remote", "set-url", "origin", f"ssh://git@127.0.0.1:{port}/x.git")
    t = time.monotonic()
    res = fetch_repo(GitRunner(), mine, 30)
    assert not res.ok and time.monotonic() - t < 10


# --- CLI as a subprocess ------------------------------------------------------------------------


def cli(*args, config: Path, check_code: int | None = None):
    cp = subprocess.run(
        [sys.executable, "-m", "repotray", "--config", str(config), *args],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    if check_code is not None:
        assert cp.returncode == check_code, cp.stdout + cp.stderr
    return cp


@pytest.fixture
def cli_setup(pair, tmp_path):
    rf, mine, theirs = pair
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"roots = ['{rf.root}']\n")
    return cfg, mine, theirs


def test_cli_status_json(cli_setup):
    cfg, mine, theirs = cli_setup
    commit(mine, "a.txt")
    make_behind(theirs, mine)
    (mine / "README").write_text("dirty\n")
    out = json.loads(cli("status", "--json", config=cfg, check_code=0).stdout)
    assert out["version"] == 1
    assert out["counts"]["total"] == 2 and out["counts"]["diverged"] == 1
    assert out["counts"]["dirty"] == 1
    repo = next(r for r in out["repos"] if r["name"] == "mine")
    assert repo["ahead"] == 1 and repo["behind"] == 1 and repo["dirty"] and repo["unstaged"] == 1
    assert set(repo) == {
        "path", "name", "branch", "upstream", "ahead", "behind", "staged", "unstaged",
        "untracked", "unmerged", "dirty", "detached", "no_upstream", "upstream_gone",
        "operation", "fetch_error", "status_error",
    }  # fmt: skip


def test_cli_scan_and_table(cli_setup):
    cfg, mine, _ = cli_setup
    out = cli("scan", "--absolute", config=cfg, check_code=0).stdout.split()
    assert str(mine.resolve()) in out and len(out) == 2
    table = cli("status", config=cfg, check_code=0).stdout
    assert table.splitlines()[0].split() == ["NAME", "BRANCH", "↑", "↓", "STATE", "PATH"]


def test_cli_actions_and_exit_codes(cli_setup):
    cfg, mine, theirs = cli_setup
    commit(mine, "a.txt")
    cli("push", "mine", config=cfg, check_code=0)
    assert status(mine).ahead == 0
    cli("push", "nope", config=cfg, check_code=2)
    make_behind(theirs, mine)
    cli("pull", str(mine), config=cfg, check_code=0)
    assert status(mine).behind == 0
    git(theirs, "pull", "-q", "--ff-only")
    commit(mine, "README", "mine\n")
    commit(theirs, "README", "theirs\n")
    git(theirs, "push", "-q")
    git(mine, "fetch", "-q")
    cp = cli("sync", "mine", config=cfg, check_code=1)
    assert "conflicts" in cp.stderr
    cli("sync", config=cfg, check_code=2)
    cli("sync", "--all", "mine", config=cfg, check_code=2)


def test_cli_sync_all_and_fetch(cli_setup):
    cfg, mine, theirs = cli_setup
    commit(mine, "a.txt")
    commit(theirs, "b.txt")
    git(theirs, "push", "-q")
    cp = cli("fetch", config=cfg, check_code=0)
    assert "mine" in cp.stdout
    cli("sync", "--all", config=cfg, check_code=0)
    assert status(mine).ahead == 0 and status(mine).behind == 0
    git(mine, "remote", "set-url", "origin", "/nonexistent/remote.git")
    cli("fetch", "mine", config=cfg, check_code=1)


def test_cli_push_all_and_pull_all(remote_fixture, tmp_path):
    a = remote_fixture.clone("a")
    b = remote_fixture.clone("b")
    commit(a, "a.txt")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f"roots = ['{remote_fixture.root}']\n")
    cli("push", "--all", "a", config=cfg, check_code=2)
    cp = cli("pull", "--all", config=cfg, check_code=0)
    assert "Nothing to pull" in cp.stdout
    cli("push", "--all", config=cfg, check_code=0)
    assert status(a).ahead == 0
    git(b, "fetch", "-q")
    assert status(b).behind == 1
    cp = cli("pull", "--all", config=cfg, check_code=0)
    assert "Pulled 1 commit" in cp.stdout
    assert status(b).behind == 0


def test_cli_ambiguous_name(remote_fixture, tmp_path):
    (remote_fixture.root / "a").mkdir()
    (remote_fixture.root / "b").mkdir()
    subprocess.run(
        ["git", "clone", "-q", str(remote_fixture.remote), str(remote_fixture.root / "a/tool")],
        check=True,
    )
    subprocess.run(
        ["git", "clone", "-q", str(remote_fixture.remote), str(remote_fixture.root / "b/tool")],
        check=True,
    )
    cfg = tmp_path / "c.toml"
    cfg.write_text(f"roots = ['{remote_fixture.root}']\n")
    cp = cli("push", "tool", config=cfg, check_code=2)
    assert "ambiguous" in cp.stderr and "a/tool" in cp.stderr
    cli("push", "a/tool", config=cfg, check_code=1)  # resolves, nothing to push


def test_cli_config_error_exit_code(tmp_path):
    cfg = tmp_path / "bad.toml"
    cfg.write_text("roots = [\n")
    cli("status", config=cfg, check_code=2)


def test_cli_misc(tmp_path):
    cfg = tmp_path / "c.toml"
    assert cli("config", "path", config=cfg, check_code=0).stdout.strip() == str(cfg)
    assert "[indicator]" in cli("config", "default", config=cfg, check_code=0).stdout
    cli("quit", config=cfg, check_code=1)
    assert cli("--version", config=cfg, check_code=0).stdout.strip() == "0.1.0"


def test_incoming_commits(pair):
    from repotray.core.gitstatus import incoming_commits

    _, mine, theirs = pair
    assert incoming_commits(GitRunner(), mine).total == 0
    git(
        theirs,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "First subject",
        "-m",
        "Body line one\n\nmore",
    )
    commit(theirs, "x.txt", msg="Second subject")
    git(theirs, "push", "-q")
    git(mine, "fetch", "-q")
    log = incoming_commits(GitRunner(), mine)
    assert log.error is None and log.total == 2
    assert [c.subject for c in log.commits] == ["Second subject", "First subject"]
    assert log.commits[1].body == "Body line one\n\nmore"
    assert log.commits[0].author == "Test User" and len(log.commits[0].sha) == 40
    assert "Second subject" in log.text and "Body line one" in log.text
    assert incoming_commits(GitRunner(), mine, limit=1).total == 2
    assert len(incoming_commits(GitRunner(), mine, limit=1).commits) == 1
    git(mine, "checkout", "-q", "-b", "local-only")
    assert incoming_commits(GitRunner(), mine).error  # no upstream
