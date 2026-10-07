import os
import sys
import time
from pathlib import Path

import pytest

from repotray.core.actions import (
    ActionContext,
    RepoLocks,
    SyncAllPlan,
    plan_sync_all,
    run_action,
    summarize_sync_all,
)
from repotray.core.gitrun import (
    CallKind,
    GitResult,
    GitRunner,
    first_line,
    git_environment,
    strip_credentials,
)
from repotray.core.types import ActionKind, ActionResult, RepoInfo, RepoState


def test_environment_never_prompts(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = git_environment(CallKind.FETCH, base={"PATH": "/bin", "SSH_ASKPASS": "x"})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
    assert env["GIT_SSH_COMMAND"] == "ssh -oBatchMode=yes"
    assert env["GIT_EDITOR"] == env["GIT_SEQUENCE_EDITOR"] == "true"
    assert env["GIT_MERGE_AUTOEDIT"] == "no"
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    if os.name == "posix":
        assert env["GIT_ASKPASS"] == "true" and "SSH_ASKPASS" not in env
    assert "GIT_OPTIONAL_LOCKS" not in env
    assert git_environment(CallKind.STATUS, base={})["GIT_OPTIONAL_LOCKS"] == "0"
    user = git_environment(CallKind.FETCH, base={"GIT_SSH_COMMAND": "ssh -i k"})
    assert user["GIT_SSH_COMMAND"] == "ssh -i k"


def test_runner_command_and_missing_git(tmp_path):
    r = GitRunner(git="definitely-not-git-xyz")
    res = r(["status"], tmp_path, 5, kind=CallKind.STATUS)
    assert res.returncode == 127 and not res.ok
    assert GitRunner().command(["status"], Path("/x"))[:7] == (
        "git",
        "-C",
        "/x",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
    )


@pytest.mark.skipif(sys.platform == "win32", reason="shebang script")
def test_runner_timeout_kills_group(tmp_path):
    script = tmp_path / "fake-git"
    script.write_text(f"#!{sys.executable}\nimport time, subprocess, sys\n"
                      "subprocess.Popen(['sleep', '30'])\ntime.sleep(30)\n")  # fmt: skip
    script.chmod(0o755)
    r = GitRunner(git=str(script))
    t = time.monotonic()
    res = r(["x"], tmp_path, 0.5, kind=CallKind.ACTION)
    assert res.timed_out and time.monotonic() - t < 5
    assert "timed out" in res.err


def test_first_line_and_credentials():
    assert first_line("\nerror: failed to push\nhint: x") == "failed to push"
    assert first_line("", "fatal: bad thing") == "bad thing"
    assert first_line("remote: fatal: nope") == "nope"
    assert strip_credentials("https://user:pw@host/x.git and ssh://u@h/y") == (
        "https://host/x.git and ssh://h/y"
    )


def state(name, **kw):
    p = Path("/r") / name
    base = dict(branch="main", upstream="origin/main", upstream_remote="origin")
    base.update(kw)
    return RepoState(info=RepoInfo(p, p / ".git", name), **base)


def test_plan_sync_all():
    plan = plan_sync_all(
        [
            state("a", ahead=1),
            state("b", behind=2),
            state("c", ahead=1, behind=1),
            state("d", ahead=1, behind=1, unstaged=1),
            state("e", ahead=1, behind=1, untracked=1),
            state("f"),
            state("g", ahead=1, operation="rebase"),
        ]
    )
    assert [(k.value, i.name) for k, i in plan.jobs] == [
        ("push", "a"),
        ("pull", "b"),
        ("sync", "c"),
        ("sync", "e"),
    ]
    assert plan.skipped == (("d", "Commit or stash first"), ("g", "Operation in progress: rebase"))


def test_summary_text():
    plan = SyncAllPlan(jobs=(), skipped=(("notes", "Commit or stash first"),))
    rs = [
        ActionResult(Path("/a"), ActionKind.PUSH, True, "ok", name="a"),
        ActionResult(Path("/b"), ActionKind.PULL, False, "bad", name="b"),
    ]
    s = summarize_sync_all(plan, rs, 0, 1)
    assert s.message == "Synced 1 of 2 · 1 failed · 1 skipped (commit or stash first: notes)"
    assert not s.ok
    assert summarize_sync_all(SyncAllPlan((), ()), [], 0, 0).message == "Nothing to sync"


class Recorder:
    def __init__(self, status: bytes):
        self.status = status
        self.calls = []

    def __call__(self, args, cwd, timeout, *, kind):
        self.calls.append(args[0])
        if args[0] == "status":
            return GitResult(0, self.status, b"", False, ())
        if args[0] == "config":
            return GitResult(0, b"branch.main.remote origin\n", b"", False, ())
        raise AssertionError(f"unexpected git call {args}")


def test_sync_refused_with_tracked_changes_without_running_git(tmp_path):
    status = (
        b"# branch.oid " + b"1" * 40 + b"\0# branch.head main\0# branch.upstream origin/main\0"
        b"# branch.ab +1 -1\0" + b"1 .M N... 100644 100644 100644 " + b"1" * 40 + b" "
        + b"1" * 40 + b" f\0"
    )  # fmt: skip
    rec = Recorder(status)
    info = RepoInfo(tmp_path, tmp_path / ".git", "x")
    res = run_action(ActionContext(runner=rec), ActionKind.SYNC, info)
    assert not res.ok and res.message == "Commit or stash first"
    assert rec.calls == ["status", "config"]


def test_busy_lock(tmp_path):
    locks = RepoLocks()
    info = RepoInfo(tmp_path, tmp_path / ".git", "x")
    with locks.hold(tmp_path) as ok:
        assert ok
        res = run_action(
            ActionContext(runner=Recorder(b""), locks=locks),
            ActionKind.PUSH,
            info,
            lock_timeout=0.1,
        )
    assert not res.ok and res.message.startswith("busy")
