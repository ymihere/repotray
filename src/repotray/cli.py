"""Command line interface (SPEC §8, PLAN §4.14). Headless: never imports a GUI toolkit."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform as pyplatform
import shutil
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from repotray import __version__
from repotray.core import config as cfgmod
from repotray.core.actions import ActionContext, RepoLocks, plan_bulk, run_action, smart_kind
from repotray.core.config import abbreviate
from repotray.core.gitrun import GitRunner, git_version
from repotray.core.gitstatus import apply_fetch_result, check_status, fetch_repo
from repotray.core.indicator import counts
from repotray.core.scanner import scan
from repotray.core.types import ActionKind, ActionResult, RepoInfo, RepoState, Snapshot
from repotray.platform import current

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

log = logging.getLogger("repotray")


# --- helpers -------------------------------------------------------------------------------------


def config_path(args) -> Path:
    if getattr(args, "config", None):
        return Path(args.config).expanduser()
    env = os.environ.get("REPOTRAY_CONFIG")
    if env:
        return Path(env).expanduser()
    return current().config_path()


def load_config(args) -> cfgmod.Config:
    path = config_path(args)
    try:
        cfg, warnings = cfgmod.load(path)
    except cfgmod.ConfigError as exc:
        raise SystemExit(_die(f"config error: {exc}", EXIT_USAGE)) from None
    for w in warnings:
        print(f"repotray: config: {w}", file=sys.stderr)
    return cfg


def _die(msg: str, code: int) -> int:
    print(f"repotray: {msg}", file=sys.stderr)
    return code


def make_runner() -> GitRunner:
    p = current()
    return GitRunner(extra_env=p.git_env(), popen_kwargs=p.popen_kwargs, kill_tree=p.kill_tree)


def require_git() -> None:
    if git_version() is None:
        raise SystemExit(_die("git not found on PATH", EXIT_FAILED))


def status_all(cfg: cfgmod.Config, runner, infos: list[RepoInfo]) -> list[RepoState]:
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        return list(
            pool.map(
                lambda i: check_status(runner, i, count_untracked=cfg.count_untracked_as_dirty),
                infos,
            )
        )


def state_words(s: RepoState, cfg: cfgmod.Config) -> list[str]:
    words = []
    if s.diverged:
        words.append("diverged")
    else:
        if s.pushable:
            words.append("push")
        if s.pullable:
            words.append("pull")
    if s.dirty(cfg.count_untracked_as_dirty):
        words.append("dirty")
    if s.detached:
        words.append("detached")
    elif s.upstream_gone:
        words.append("upstream gone")
    elif s.no_upstream:
        words.append("no upstream")
    if s.operation:
        words.append(s.operation)
    if s.fetch_error:
        words.append("fetch failed")
    if s.status_error:
        words.append("error")
    return words or ["clean"]


def print_table(states: list[RepoState], cfg: cfgmod.Config, out=sys.stdout) -> None:
    rows = [("NAME", "BRANCH", "↑", "↓", "STATE", "PATH")]
    for s in states:
        branch = s.branch or ("(detached)" if s.detached else "?")
        rows.append(
            (
                s.name,
                branch,
                str(s.ahead) if s.has_upstream else "-",
                str(s.behind) if s.has_upstream else "-",
                ",".join(state_words(s, cfg)),
                abbreviate(s.path),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip(), file=out)


def status_json(snapshot: Snapshot, cfg: cfgmod.Config) -> dict:
    c = counts(snapshot, cfg)
    return {
        "version": 1,
        "generated_at": datetime.fromtimestamp(snapshot.generated_at, UTC).isoformat(),
        "counts": {
            "push": c.push,
            "pull": c.pull,
            "dirty": c.dirty,
            "diverged": c.diverged,
            "no_upstream": c.no_upstream,
            "detached": c.detached,
            "fetch_failed": c.fetch_failed,
            "total": c.total,
        },
        "repos": [
            {
                "path": str(s.path),
                "name": s.name,
                "branch": s.branch,
                "upstream": s.upstream,
                "ahead": s.ahead,
                "behind": s.behind,
                "staged": s.staged,
                "unstaged": s.unstaged,
                "untracked": s.untracked,
                "unmerged": s.unmerged,
                "dirty": s.dirty(cfg.count_untracked_as_dirty),
                "detached": s.detached,
                "no_upstream": s.no_upstream,
                "upstream_gone": s.upstream_gone,
                "operation": s.operation,
                "fetch_error": s.fetch_error,
                "status_error": s.status_error,
            }
            for s in snapshot.repos
        ],
    }


def resolve_repos(names: list[str], infos: list[RepoInfo]) -> tuple[list[RepoInfo], list[str]]:
    """Map CLI arguments to repos. Returns (found, error messages)."""
    found: list[RepoInfo] = []
    errors: list[str] = []
    for arg in names:
        matches = [i for i in infos if i.name == arg]
        if not matches:
            matches = [i for i in infos if i.path.name == arg]
        if not matches:
            p = Path(arg).expanduser()
            if p.exists():
                rp = p.resolve()
                matches = [i for i in infos if i.path == rp]
        if not matches:
            errors.append(f"{arg}: no such repository (see `repotray scan`)")
        elif len(matches) > 1:
            cands = ", ".join(f"{m.name} ({abbreviate(m.path)})" for m in matches)
            errors.append(f"{arg}: ambiguous, candidates: {cands}")
        elif matches[0] not in found:
            found.append(matches[0])
    return found, errors


def scan_or_explicit(cfg: cfgmod.Config, runner, names: list[str]) -> list[RepoInfo]:
    """Scan; then add path arguments that are repos outside the roots."""
    infos, warnings = scan(cfg, runner, workers=cfg.workers)
    for w in warnings:
        log.info("%s", w)
    known = {i.path for i in infos}
    extra = []
    for arg in names:
        p = Path(arg).expanduser()
        if p.is_dir() and (p / ".git").exists() and p.resolve() not in known:
            extra.append(str(p.resolve()))
    if extra:
        more, _ = scan(
            cfgmod.Config(roots=(), repos=tuple(extra), max_depth=0), runner, workers=cfg.workers
        )
        infos += more
    return infos


def print_result(r: ActionResult) -> None:
    mark = "ok  " if r.ok else "FAIL"
    stream = sys.stdout if r.ok else sys.stderr
    print(f"{mark} {r.action.value:5} {r.name}: {r.message}", file=stream)
    if not r.ok and log.isEnabledFor(logging.DEBUG):
        for c in r.command:
            print(f"     $ {c}", file=sys.stderr)
        if r.stderr:
            print("     " + r.stderr.strip().replace("\n", "\n     "), file=sys.stderr)


# --- commands ------------------------------------------------------------------------------------


def cmd_status(args) -> int:
    if args.demo:
        from repotray.core.demo import demo_snapshot

        cfg = cfgmod.Config()
        snap = demo_snapshot()
    else:
        cfg = load_config(args)
        require_git()
        runner = make_runner()
        infos, warnings = scan(cfg, runner, workers=cfg.workers)
        for w in warnings:
            print(f"repotray: {w}", file=sys.stderr)
        states = status_all(cfg, runner, infos)
        snap = Snapshot(repos=tuple(states), generated_at=time.time())
    if args.json:
        json.dump(status_json(snap, cfg), sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print_table(list(snap.repos), cfg)
    return EXIT_OK


def cmd_scan(args) -> int:
    cfg = load_config(args)
    require_git()
    infos, warnings = scan(cfg, make_runner(), workers=cfg.workers)
    for w in warnings:
        print(f"repotray: {w}", file=sys.stderr)
    for i in sorted(infos, key=lambda i: str(i.path)):
        print(str(i.path) if args.absolute else abbreviate(i.path))
    return EXIT_OK


def cmd_fetch(args) -> int:
    cfg = load_config(args)
    require_git()
    runner = make_runner()
    infos = scan_or_explicit(cfg, runner, args.repos)
    if args.repos:
        targets, errors = resolve_repos(args.repos, infos)
        for e in errors:
            print(f"repotray: {e}", file=sys.stderr)
        if errors:
            return EXIT_USAGE
    else:
        targets = [i for i in infos if i.fetch_enabled]

    now = time.time()
    with ThreadPoolExecutor(max_workers=cfg.fetch_workers) as pool:
        results = list(pool.map(lambda i: fetch_repo(runner, i.path, cfg.fetch_timeout), targets))
    states = {s.path: s for s in status_all(cfg, runner, targets)}
    failed = 0
    for info, res in zip(targets, results, strict=True):
        st = apply_fetch_result(states[info.path], res, now)
        states[info.path] = st
        if st.fetch_error:
            failed += 1
            print(f"repotray: fetch failed: {info.name}: {st.fetch_error}", file=sys.stderr)
    print_table(sorted(states.values(), key=lambda s: s.name.casefold()), cfg)
    return EXIT_FAILED if failed else EXIT_OK


def _run_actions(args, cfg, runner, jobs: list[tuple[ActionKind, RepoInfo]]) -> int:
    ctx = ActionContext(
        runner=runner,
        timeout=float(cfg.action_timeout),
        sync_strategy=cfg.sync_strategy,
        locks=RepoLocks(),
    )
    with ThreadPoolExecutor(max_workers=cfg.fetch_workers) as pool:
        results = list(pool.map(lambda j: run_action(ctx, j[0], j[1]), jobs))
    for r in results:
        print_result(r)
    return EXIT_OK if all(r.ok for r in results) else EXIT_FAILED


def _run_bulk(args, cfg, runner, kind: ActionKind, infos: list[RepoInfo]) -> int:
    """`push --all` / `pull --all` / `sync --all`: same plan as the panel's buttons."""
    plan = plan_bulk(kind, status_all(cfg, runner, infos))
    for name, reason in plan.skipped:
        print(f"skip {kind.value:5} {name}: {reason}")
    if not plan.jobs:
        print(f"Nothing to {'push or pull' if kind is ActionKind.SYNC else kind.value}")
        return EXIT_OK
    return _run_actions(args, cfg, runner, list(plan.jobs))


def cmd_action(args) -> int:
    kind = ActionKind(args.command)
    if args.all == bool(args.repos):
        return _die(f"{kind.value} needs --all or at least one REPO (not both)", EXIT_USAGE)
    cfg = load_config(args)
    require_git()
    runner = make_runner()
    infos = scan_or_explicit(cfg, runner, args.repos)
    if args.all:
        return _run_bulk(args, cfg, runner, kind, infos)
    targets, errors = resolve_repos(args.repos, infos)
    for e in errors:
        print(f"repotray: {e}", file=sys.stderr)
    if errors:
        return EXIT_USAGE
    return _run_actions(args, cfg, runner, [(kind, i) for i in targets])


def cmd_sync(args) -> int:
    if args.all == bool(args.repos):
        return _die("sync needs --all or at least one REPO (not both)", EXIT_USAGE)
    cfg = load_config(args)
    require_git()
    runner = make_runner()
    infos = scan_or_explicit(cfg, runner, args.repos)
    if args.all:
        return _run_bulk(args, cfg, runner, ActionKind.SYNC, infos)
    targets, errors = resolve_repos(args.repos, infos)
    for e in errors:
        print(f"repotray: {e}", file=sys.stderr)
    if errors:
        return EXIT_USAGE
    jobs = []
    for s in status_all(cfg, runner, targets):
        kind = smart_kind(s)
        if kind is None:
            print(f"ok   -     {s.name}: nothing to do")
            continue
        jobs.append((kind, s.info))
    if not jobs:
        return EXIT_OK
    return _run_actions(args, cfg, runner, jobs)


def cmd_doctor(args) -> int:
    from repotray.backends import registry

    p = current()
    path = config_path(args)
    print(f"repotray {__version__}")
    print(f"python   {sys.version.split()[0]} ({sys.executable})")
    print(f"system   {pyplatform.system()} {pyplatform.release()}")
    for k, v in p.desktop_info().items():
        print(f"  {k}: {v}")
    print(f"git      {git_version() or 'NOT FOUND'}")
    print(f"config   {path}{'' if path.exists() else ' (missing: defaults in use)'}")
    try:
        cfg, warnings = cfgmod.load(path)
        for w in warnings:
            print(f"  warning: {w}")
    except cfgmod.ConfigError as exc:
        print(f"  ERROR: {exc}")
        cfg = cfgmod.Config()
    print(f"roots    {', '.join(cfg.roots) or '(none)'}")
    if git_version():
        t0 = time.monotonic()
        infos, warnings = scan(cfg, make_runner(), workers=cfg.workers)
        print(f"  {len(infos)} repositories found in {time.monotonic() - t0:.2f} s")
        for w in warnings:
            print(f"  warning: {w}")
    print(f"icons    {p.icons_installed()}")
    print(f"autostart {'enabled' if p.autostart_enabled() else 'disabled'}")
    print(f"log      {p.log_path()}")
    print("backends")
    chosen, rows = registry.describe(p, cfg.backend, getattr(args, "backend", None))
    for name, score, reason in rows:
        mark = "*" if name == chosen else " "
        print(f"  {mark} {name:14} {score:4}  {reason}")
    if chosen is None:
        print("  no usable backend found")
    return EXIT_OK


def cmd_config(args) -> int:
    if args.what == "path":
        print(config_path(args))
    else:
        sys.stdout.write(cfgmod.default_text())
    return EXIT_OK


def tray_argv() -> list[str]:
    """How autostart should launch the tray (a platform may know better, e.g. Windows: no
    console window)."""
    own = getattr(current(), "tray_argv", None)
    if own is not None:
        return own()
    launcher = shutil.which("repotray")
    if launcher:
        return [str(Path(launcher).absolute()), "tray"]
    return [sys.executable, "-m", "repotray", "tray"]


def cmd_autostart(args) -> int:
    p = current()
    if args.what == "enable":
        try:
            argv = tray_argv()
        except OSError as exc:
            return _die(f"cannot enable autostart: {exc}", EXIT_FAILED)
        print(f"autostart enabled: {p.autostart_enable(argv)}")
    elif args.what == "disable":
        p.autostart_disable()
        print("autostart disabled")
    else:
        print("enabled" if p.autostart_enabled() else "disabled")
    return EXIT_OK


def icon_source() -> Path:
    return Path(str(resources.files("repotray").joinpath("icons/data/symbolic")))


def cmd_icons(args) -> int:
    p = current()
    if args.what == "install":
        copied = p.install_icons(icon_source())
        print(f"{len(copied)} icon files installed or updated; {p.icons_installed()}")
    else:
        removed = p.uninstall_icons()
        print(f"{len(removed)} icon files removed")
    return EXIT_OK


def cmd_quit(args) -> int:
    p = current()
    lock = p.lock_path()
    held = p.acquire_instance_lock(lock)
    if held is not None:
        held.release()
        return _die("not running", EXIT_FAILED)
    pid = p.read_lock_pid(lock)
    if pid is None:
        return _die("running, but its pid is unknown", EXIT_FAILED)
    if os.name == "nt":
        return _die("quit is not supported on Windows; use the tray menu", EXIT_FAILED)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return _die("not running", EXIT_FAILED)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        held = p.acquire_instance_lock(lock)
        if held is not None:
            held.release()
            print(f"stopped repotray (pid {pid})")
            return EXIT_OK
        time.sleep(0.1)
    return _die(f"pid {pid} did not exit within 5 s", EXIT_FAILED)


def cmd_tray(args) -> int:
    from repotray.app import run_tray

    return run_tray(
        config_file=config_path(args),
        demo=args.demo,
        backend=getattr(args, "backend", None),
        verbose=bool(getattr(args, "verbose", False)),
    )


# --- parser --------------------------------------------------------------------------------------


def _globals(p: argparse.ArgumentParser, suppress: bool) -> None:
    d = {"default": argparse.SUPPRESS} if suppress else {}
    p.add_argument("--config", metavar="PATH", help="config file to use", **d)
    p.add_argument("-v", "--verbose", action="store_true", help="debug output on stderr", **d)
    p.add_argument("--backend", metavar="NAME", help="tray backend (see `doctor`)", **d)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repotray",
        description="Tray indicator for the state of your local git clones.",
    )
    p.add_argument("--version", action="version", version=__version__)
    _globals(p, suppress=False)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    def add(name: str, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        _globals(sp, suppress=True)
        return sp

    sp = add("tray", "start the tray (default)")
    sp.add_argument("--demo", action="store_true", help="show fabricated repositories")
    sp.set_defaults(func=cmd_tray)

    sp = add("status", "one status pass; print a table or JSON")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--demo", action="store_true", help="fabricated repositories")
    sp.set_defaults(func=cmd_status)

    sp = add("scan", "list discovered repositories")
    sp.add_argument("--absolute", action="store_true", help="print absolute paths")
    sp.set_defaults(func=cmd_scan)

    sp = add("fetch", "fetch (all or the given repos), then print status")
    sp.add_argument("repos", nargs="*", metavar="REPO")
    sp.set_defaults(func=cmd_fetch)

    for name, help, every in (
        ("push", "git push to the upstream", "every repo that is only ahead (Push all)"),
        ("pull", "git pull --ff-only", "every repo that is only behind (Pull all)"),
    ):
        sp = add(name, help)
        sp.add_argument("--all", action="store_true", help=every)
        sp.add_argument("repos", nargs="*", metavar="REPO", help="name, basename or path")
        sp.set_defaults(func=cmd_action)

    sp = add("sync", "push if ahead, pull if behind, pull --rebase + push if diverged")
    sp.add_argument("--all", action="store_true", help="every repository (Sync all)")
    sp.add_argument("repos", nargs="*", metavar="REPO")
    sp.set_defaults(func=cmd_sync)

    sp = add("doctor", "environment, config, backends and icons report")
    sp.set_defaults(func=cmd_doctor)

    sp = add("config", "config file location or the default config")
    sp.add_argument("what", choices=["path", "default"])
    sp.set_defaults(func=cmd_config)

    sp = add("autostart", "start the tray at login")
    sp.add_argument("what", choices=["enable", "disable", "status"])
    sp.set_defaults(func=cmd_autostart)

    sp = add("icons", "install or remove the user icon theme files (Linux)")
    sp.add_argument("what", choices=["install", "uninstall"])
    sp.set_defaults(func=cmd_icons)

    sp = add("quit", "stop the running tray")
    sp.set_defaults(func=cmd_quit)
    return p


def utf8_output(streams=None) -> None:
    """Windows writes pipes and files in the ANSI code page (cp1252), which has no ↑ ↓ ✎ and
    makes print() fail: write UTF-8 there, as the console shows it (and as Python 3.15 will by
    default). Consoles and other systems are left alone."""
    if os.name != "nt":
        return
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if stream is not None and enc != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args([*(argv if argv is not None else sys.argv[1:]), "tray"])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="repotray: %(levelname)s: %(message)s",
    )
    try:
        return args.func(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_FAILED
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return EXIT_OK
