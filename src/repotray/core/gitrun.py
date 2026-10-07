"""The one place that spawns git.

Every git process gets a non-interactive environment (it can never prompt for credentials or open
an editor), runs in its own process group and is killed with its children on timeout.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class CallKind(StrEnum):
    STATUS = "status"  # read-only, never takes optional locks
    FETCH = "fetch"
    ACTION = "action"
    QUERY = "query"  # rev-parse, config and other cheap reads


@dataclass(frozen=True, slots=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool
    command: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def out(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def err(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], cwd: Path, timeout: float, *, kind: CallKind
    ) -> GitResult: ...


NON_INTERACTIVE_ENV: Mapping[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_EDITOR": "true",
    "GIT_SEQUENCE_EDITOR": "true",
    "GIT_MERGE_AUTOEDIT": "no",
    "SSH_ASKPASS_REQUIRE": "never",
}


def git_environment(
    kind: CallKind,
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(extra or {})
    env.update(NON_INTERACTIVE_ENV)
    if "GIT_SSH_COMMAND" not in env:
        env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes"
    if os.name == "posix":
        env["GIT_ASKPASS"] = "true"
        env.pop("SSH_ASKPASS", None)
    if kind is CallKind.STATUS:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    # Translations would break parsing of messages we show; keep git's output in English.
    env["LC_ALL"] = "C"
    env.pop("LANGUAGE", None)
    return env


def default_popen_kwargs() -> dict:
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        return {"creationflags": flags}
    return {"start_new_session": True}


def default_kill_tree(proc: subprocess.Popen) -> None:
    """Terminate a process and everything it spawned."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)


class GitRunner:
    """Callable runner: ``runner(args, cwd, timeout, kind=...) -> GitResult``."""

    def __init__(
        self,
        extra_env: Mapping[str, str] | None = None,
        popen_kwargs: Callable[[], dict] = default_popen_kwargs,
        kill_tree: Callable[[subprocess.Popen], None] = default_kill_tree,
        git: str = "git",
    ) -> None:
        self.extra_env = dict(extra_env or {})
        self.popen_kwargs = popen_kwargs
        self.kill_tree = kill_tree
        self.git = git
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self._closed = False

    def command(self, args: Sequence[str], cwd: Path) -> tuple[str, ...]:
        return (
            self.git,
            "-C",
            str(cwd),
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            *args,
        )

    def __call__(
        self, args: Sequence[str], cwd: Path, timeout: float, *, kind: CallKind
    ) -> GitResult:
        cmd = self.command(args, cwd)
        if self._closed:
            return GitResult(-1, b"", b"repotray is shutting down", False, cmd)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=git_environment(kind, extra=self.extra_env),
                **self.popen_kwargs(),
            )
        except FileNotFoundError:
            return GitResult(127, b"", b"git: command not found", False, cmd)
        except OSError as exc:
            return GitResult(126, b"", str(exc).encode(), False, cmd)
        with self._lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
            return GitResult(proc.returncode, out, err, False, cmd)
        except subprocess.TimeoutExpired:
            self.kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
            msg = f"timed out after {timeout:g} s".encode()
            return GitResult(-9, out, (err + b"\n" + msg).strip(), True, cmd)
        finally:
            with self._lock:
                self._procs.discard(proc)

    def kill_all(self) -> None:
        """Stop accepting work and kill every running git process (shutdown)."""
        self._closed = True
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            self.kill_tree(p)


_available: dict[str, str | None] = {}
_available_lock = threading.Lock()


def git_version(git: str = "git") -> str | None:
    """`git --version` output, cached; None when git is missing."""
    with _available_lock:
        if git in _available:
            return _available[git]
        version = None
        if shutil.which(git):
            try:
                cp = subprocess.run(
                    [git, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
                if cp.returncode == 0:
                    version = cp.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                version = None
        _available[git] = version
        return version


def git_available(git: str = "git") -> bool:
    return git_version(git) is not None


_PREFIXES = ("error: ", "fatal: ", "hint: ", "remote: ", "warning: ")


def first_line(stderr: str, stdout: str = "") -> str:
    """The first meaningful line of git's output, with level prefixes stripped."""
    for text in (stderr, stdout):
        for raw in text.splitlines():
            line = raw.strip()
            changed = True
            while changed:
                changed = False
                for p in _PREFIXES:
                    if line.lower().startswith(p):
                        line = line[len(p) :].strip()
                        changed = True
            if line:
                return line
    return ""


def strip_credentials(text: str) -> str:
    """Remove user:password@ from URLs before logging or showing them."""
    return re.sub(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1", text, flags=re.I)
