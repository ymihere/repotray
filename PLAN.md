# repotray — implementation plan

This is the work order for building repotray **end to end, unattended**. It is written for an
autonomous coding agent; the maintainer is not available to answer questions while it runs.

Read in this order: `CLAUDE.md` → `CLAUDE.local.md` (dev machine facts and private-data rules; may be
absent on other machines) → `SPEC.md` (behaviour) → this file (structure, interfaces, order, checks).

**Precedence.** SPEC.md defines *what* repotray does. PLAN.md defines *how* it is built and settles
everything SPEC left open. Where they disagree, PLAN.md is newer: implement PLAN.md and fix SPEC.md in
the same commit. **Exception:** changes the maintainer requested after 0.1.0 (2026-10-07: ▲/▼ arrow
markers, one panel row per repo with `panel_sort`, Push all / Pull all / Sync all at the top of the
panel) are specified in SPEC.md and logged in docs/decisions.md; where this plan still describes the
earlier dots-only icons, zipped rows or the footer, SPEC.md wins.

---

## 0. Ground rules

### 0.1 Safety — non-negotiable
1. **Never modify a repository you did not create**, except the repotray project repo itself (your own
   commits). Concretely: no push, pull, sync, commit, stash, checkout, reset, rebase or merge on the
   maintainer's real repos. Read-only use of the real roots is allowed: `repotray scan`, `status`,
   `doctor`, and a handful of `fetch` runs. Never click action buttons in a panel that shows real repos.
   All action testing uses temporary fixture repos or `--demo`.
2. **Never publish.** No `git push`, no `gh repo create`, no GitHub API writes, no PyPI upload. The
   maintainer publishes (RELEASING.md tells them how).
3. **Never change global state you don't own:** no edits to the global git config, GTK/Cinnamon
   settings, or system packages; no `sudo`. User-level files under `~` only where this plan says so,
   and every one of them must be removable by `scripts/uninstall.sh` or the test that created it.
4. **Leave no stray processes or windows.** Kill every tray instance you start. The only exception is
   the single installed instance left running at the very end (M6).
5. **Tests isolate git and XDG:** `GIT_CONFIG_GLOBAL=<tmp>/gitconfig` (with user.name, user.email,
   `init.defaultBranch=main`, `commit.gpgsign=false`), `GIT_CONFIG_NOSYSTEM=1`, and `XDG_CONFIG_HOME`,
   `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME` pointed into `tmp_path` for anything touching
   config, logs, icons or autostart.
6. **Privacy:** real repository names and paths never appear in committed files, fixtures, docs,
   screenshots or commit messages (see CLAUDE.local.md). Screenshots for docs come from `--demo`, cropped
   to repotray's own icon, label and windows.

### 0.2 Working style
- Work milestone by milestone, M0 → M6 (§5). Each milestone ends with: tests green, `ruff check` and
  `ruff format --check` clean, CLAUDE.md "Status" updated, one commit `M<n>: <summary>`. Follow your
  harness's commit attribution instructions.
- **Ambiguity:** choose the simplest option consistent with SPEC.md, implement it, and append an entry to
  `docs/decisions.md` (date, question, choice, reason). Do not stop to ask.
- **Blocked:** if something is impossible in this environment, record it in `docs/decisions.md` under
  "Blocked / unverified", do everything else, and list it in the hand-off (M6).
- Verify GUI work by looking at it: take screenshots (CLAUDE.local.md has the recipe) and read the PNG.
  Iterate until it matches SPEC §2.5. "It runs without errors" is not verification for UI.

---

## 1. Decisions that settle SPEC §11 and other gaps

| Topic | Decision |
|---|---|
| Licence | MIT, `Copyright (c) 2026 Andreas Bonelli`. Octicons' MIT notice ships alongside the icons. |
| Defaults | `fetch_interval = 600`, `notifications = false` (as in SPEC). |
| Glyph | Octicon `repo` at scale 1.0, unshifted (verified in the live tray, see CLAUDE.local.md). Path data in §4.12. |
| macOS / Windows | v1 ships the pystray backend with the **menu fallback** (`caps.panel = False`), marked *experimental, untested by the maintainer*. Native panels are the documented top porting opportunity. **Windows (2026-10-07):** the `qt` backend (PySide6, `ui/qt/`) gives the full panel and is the default there; pystray remains for macOS. |
| Badge | No counts drawn into bitmaps (unreadable at 16 px). Where no label is supported, counts live in the tooltip and menu; dots and tint work everywhere. |
| Panel theme | `panel_theme = "auto"`: on Cinnamon read `gsettings get org.cinnamon.theme name`; if it contains "dark" (case-insensitive) set `Gtk.Settings.get_default().props.gtk_application_prefer_dark_theme = True` for repotray's process only. Cinnamon popups follow the Cinnamon theme, GTK apps the GTK theme, and they differ on the dev machine. `dark` / `light` force; `system` leaves GTK alone. |
| Middle click | Fetch all now (XApp button 2). |
| Second instance | Prints `repotray is already running (pid N)` to stderr, exits 0. |
| Windows autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `repotray` (stdlib `winreg`), instead of a Startup shortcut. |
| Demo mode | `--demo` on `tray` and `status`: a fixed fabricated snapshot with generic names and simulated actions (§4.11). Used for screenshots, UI tests and porting. |
| Dirty vs. actions | Only **tracked** changes (staged, unstaged, unmerged) block Sync. Untracked files never block; git itself refuses to overwrite them. Pull is never blocked; `--ff-only` fails safely. |
| Push target | Explicit: `git push <branch.B.remote> refs/heads/B:<branch.B.merge>`. No push button when the upstream remote is `.` (local branch). |
| Repo URL | `https://github.com/ymihere/repotray` (created 2026-10-07, private until the maintainer publishes). Single constant in `pyproject.toml` and README. |
| Layout & build | `src/` layout, hatchling, distribution name `repotray`, version `0.1.0`. |
| i18n | English only in v1; all user-visible strings live in the model/ui layers, not in core logic, so gettext can be added later. |

---

## 2. Environment

Facts about the dev machine are in `CLAUDE.local.md`. Generic setup, used on every machine:

```sh
scripts/dev-setup.sh      # creates .venv (system site-packages), bootstraps pip, installs -e .[dev]
. .venv/bin/activate
pytest -q                 # unit + integration; GUI tests need REPOTRAY_GUI_TESTS=1 and a display
ruff check . && ruff format --check .
```

`dev-setup.sh` must work without pip on the system: `python3 -m venv --without-pip
--system-site-packages .venv`, then use `ensurepip` if available, else download
`https://bootstrap.pypa.io/get-pip.py` and run it with the venv's python. Idempotent.

---

## 3. Repository layout

```
repotray/
├── README.md  LICENSE  CHANGELOG.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md  RELEASING.md
├── SPEC.md  PLAN.md  CLAUDE.md          (CLAUDE.local.md and HANDOFF.md are gitignored)
├── pyproject.toml  .gitignore  .editorconfig
├── .github/
│   ├── workflows/ci.yml  workflows/release.yml
│   ├── ISSUE_TEMPLATE/bug_report.yml  platform_report.yml  feature_request.yml  config.yml
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   ├── configuration.md  cli.md  architecture.md  porting.md  troubleshooting.md  decisions.md
│   └── images/            demo screenshots only
├── scripts/
│   ├── install.sh  uninstall.sh  dev-setup.sh
│   └── dev/screenshot.py  dev/click-tray.sh  dev/preview-icons.py
├── tools/
│   ├── build_icons.py     dev-only (shapely, svgpathtools); output is committed
│   └── octicons/          repo-16.svg, git-branch-16.svg, LICENSE (verbatim upstream copies)
├── src/repotray/
│   ├── __init__.py        __version__ = "0.1.0"
│   ├── __main__.py        python -m repotray
│   ├── cli.py             argparse, subcommands, exit codes
│   ├── app.py             Controller: wires scheduler, model, backend, panel
│   ├── default_config.toml
│   ├── core/              stdlib only — no gi, no GUI, no platform-specific imports
│   │   ├── types.py       dataclasses shared by everything (§4.2)
│   │   ├── gitrun.py      the one place that spawns git (§4.3)
│   │   ├── gitstatus.py   porcelain v2 parser + status/fetch per repo (§4.4)
│   │   ├── scanner.py     discovery (§4.5)
│   │   ├── config.py      schema, load, validate, reload (§4.6)
│   │   ├── actions.py     push / pull / sync / sync-all (§4.7)
│   │   ├── scheduler.py   passes, pools, locks, backoff, resume detection (§4.8)
│   │   ├── model.py       Snapshot → PanelModel, menus (§4.9)
│   │   ├── indicator.py   Snapshot + config → IconSpec, label (§4.9)
│   │   ├── tooltip.py     Snapshot + caps → tooltip text (§4.9)
│   │   └── demo.py        demo snapshot + simulated action runner (§4.11)
│   ├── platform/          OS services behind one protocol (§4.10)
│   │   ├── __init__.py    current() → Platform
│   │   ├── base.py  linux.py  macos.py  windows.py
│   ├── backends/          tray backends behind one protocol + registry (§4.11)
│   │   ├── base.py  registry.py  fake.py
│   │   ├── xapp.py  appindicator.py  gtkstatusicon.py  qt.py  pystray_backend.py
│   ├── ui/
│   │   ├── placement.py   pure geometry for anchoring the panel (no gi)
│   │   ├── text.py        toolkit-free dialog texts shared by gtk3 and qt
│   │   ├── gtk3/          panel.py  menus.py  details.py  theme.py  (shared by the Linux backends)
│   │   └── qt/            panel.py  menus.py  dialogs.py  icons.py  widgets.py  app.py  winapi.py
│   └── icons/
│       ├── names.py       IconSpec → theme icon name
│       ├── svg.py         IconSpec → full-colour SVG (hex mode), from geometry.json
│       ├── raster.py      IconSpec → Pillow RGBA image (pystray), from geometry.json
│       └── data/          symbolic/*.svg (102 files), geometry.json, LICENSE-octicons
└── tests/
    ├── conftest.py        fixtures: git_env, repo_factory, fixture remotes, tmp XDG dirs
    ├── unit/  integration/  gui/  conformance/
```

---

## 4. Architecture and interfaces

### 4.1 Layering
`core` ← `platform` ← `app` ← `backends` / `ui`. Arrows mean "may import". `core` imports only the
standard library. `platform` imports stdlib plus lazily imported OS modules (`winreg`, `fcntl`,
`msvcrt`). Only `backends/*`, `ui/gtk3/*` and `ui/qt/*` import gi, PySide6, pystray or Pillow, always
inside the module, so importing the registry never imports a toolkit. A test
(`tests/unit/test_layering.py`) blocks `gi`, `pystray`, `PIL` and `PySide6` via
`sys.modules[...] = None` and imports every module under `core`, `platform`, `icons/names.py`,
`icons/svg.py`, `ui/placement.py`, `ui/text.py`, `cli` and `app`; it also greps those files for
toolkit imports.

### 4.2 Core types (`core/types.py`)
Frozen dataclasses with `slots=True`; times are `float` epoch seconds; paths are `pathlib.Path`.

```python
class ActionKind(StrEnum): FETCH = "fetch"; PUSH = "push"; PULL = "pull"; SYNC = "sync"

@dataclass(frozen=True, slots=True)
class RepoInfo:                    # from the scanner
    path: Path                     # absolute, resolved
    git_dir: Path                  # `git rev-parse --absolute-git-dir`, cached at scan time
    name: str                      # display name, unique within a scan (§4.5)
    fetch_enabled: bool = True

@dataclass(frozen=True, slots=True)
class RepoState:
    info: RepoInfo
    branch: str | None             # None when detached
    oid: str | None                # None for "(initial)"
    upstream: str | None           # e.g. "origin/main"
    upstream_remote: str | None    # branch.<b>.remote
    upstream_merge: str | None     # branch.<b>.merge, e.g. "refs/heads/main"
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    unmerged: int = 0
    untracked: int = 0
    detached: bool = False
    upstream_gone: bool = False    # upstream configured but ref missing
    operation: str | None = None   # "rebase" | "merge" | "cherry-pick" | "revert" | "bisect"
    status_error: str | None = None
    fetch_error: str | None = None
    fetched_at: float | None = None
    checked_at: float = 0.0
    # derived properties: tracked_changes, dirty(count_untracked), has_upstream,
    # pushable, pullable, diverged — see §4.9 for exact rules

@dataclass(frozen=True, slots=True)
class ActionResult:
    repo: Path; action: ActionKind; ok: bool; message: str   # message = first meaningful line
    command: tuple[str, ...]; stdout: str; stderr: str; started_at: float; duration: float
    restored: bool | None = None   # sync only: True when a failed sync left the repo as before

class FetchMode(StrEnum): IDLE = "idle"; FETCHING = "fetching"; PAUSED = "paused"; BACKOFF = "backoff"

@dataclass(frozen=True, slots=True)
class Snapshot:
    repos: tuple[RepoState, ...]          # sorted by name.casefold()
    generated_at: float
    fetch_mode: FetchMode
    last_fetch_pass_at: float | None
    next_fetch_at: float | None
    all_fetches_failed: bool              # → icon state "error"
    git_missing: bool                     # → icon state "error"
    running: Mapping[Path, ActionKind]    # actions in flight
    sync_all: tuple[int, int] | None      # (done, total) while Sync all runs
    recent_results: tuple[ActionResult, ...]   # newest first, at most 20
    config_warning: str | None            # shown in the panel header
```

### 4.3 Running git (`core/gitrun.py`)
All git processes go through `run_git(args, cwd, timeout, *, kind) -> GitResult(returncode, stdout,
stderr, timed_out, command)`; tests inject a fake runner through the same signature.

- Command: `["git", "-C", str(cwd), "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args]`.
- `stdin=DEVNULL`, capture stdout/stderr as bytes, decode UTF-8 with `errors="replace"` except status
  output, which the parser handles as bytes.
- Environment = `os.environ` plus `platform.git_env()` plus, for every call:
  `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `GIT_EDITOR=true`, `GIT_SEQUENCE_EDITOR=true`,
  `GIT_MERGE_AUTOEDIT=no`, `SSH_ASKPASS_REQUIRE=never`, and `GIT_SSH_COMMAND` = the repo's
  `core.sshCommand` (read with `git config --get` before each fetch/action; plain `ssh` when unset)
  plus `-oBatchMode=yes` (`-batch` for plink), unless the user set `GIT_SSH_COMMAND` or `GIT_SSH`
  (2026-10-07: replacing `core.sshCommand` with plain `ssh` would bypass e.g. Windows' OpenSSH and
  its agent). POSIX adds `GIT_ASKPASS=true` (the `true` binary on
  PATH). Status calls add `GIT_OPTIONAL_LOCKS=0` so a status pass never writes the index.
- Process group: POSIX `start_new_session=True`; Windows `CREATE_NEW_PROCESS_GROUP |
  CREATE_NO_WINDOW`. On timeout `platform.kill_tree(proc)`: POSIX SIGTERM to the group, SIGKILL after
  2 s; Windows `taskkill /T /F /PID`. Then return `timed_out=True`.
- `git_available()` caches `git --version`; if git is missing, the snapshot sets `git_missing`.
- Any message shown to the user is the first non-empty stderr line with `error: ` / `fatal: ` /
  `hint: ` prefixes stripped; the full output stays in the `ActionResult`.

### 4.4 Status and fetch per repo (`core/gitstatus.py`)
**Status:** `status --porcelain=v2 --branch -z --untracked-files=normal` (`=no` when
`count_untracked_as_dirty = false`), timeout 15 s. Parse the NUL-separated records:

| Record | Handling |
|---|---|
| `# branch.oid <sha>` / `(initial)` | `oid` / `None` |
| `# branch.head <name>` / `(detached)` | `branch` / `detached=True` |
| `# branch.upstream <name>` | `upstream` |
| `# branch.ab +A -B` | `ahead`, `behind` |
| other `# ...` | ignore (e.g. `# stash`) |
| `1 XY ...` | X ≠ `.` → staged += 1; Y ≠ `.` → unstaged += 1 |
| `2 XY ...` | same as `1`, and **the next NUL field is the original path: consume and skip it** |
| `u ...` | unmerged += 1 |
| `? path` | untracked += 1 |
| `! path` | ignore |

Upstream present but no `branch.ab` → `upstream_gone=True`. A path that itself begins with `1 `, `?`
or `#` must not confuse the parser (only the record start is inspected, and `2` records consume their
extra field). `upstream_remote` / `upstream_merge` come from one
`config --get-regexp ^branch\.<escaped>\.(remote|merge)$` call, only when `upstream` is set.
`operation` comes from file checks in `git_dir`: `rebase-merge/` or `rebase-apply/` → rebase,
`MERGE_HEAD` → merge, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `BISECT_LOG`. Non-zero exit → `status_error` =
first stderr line, other fields left at defaults.

**Fetch:** `fetch --quiet --no-write-fetch-head --recurse-submodules=no`, timeout `fetch_timeout`.
Fetches the branch's default remote; honours the user's `fetch.prune`. Success clears `fetch_error`
and sets `fetched_at`; failure sets `fetch_error`.

### 4.5 Discovery (`core/scanner.py`)
`scan(config) -> list[RepoInfo]`:
1. For each root (`~` expanded, resolved; missing roots → warning): depth 0 is the root itself. A
   directory is a repo when it contains an entry named `.git` (directory or file). Walk with
   `os.scandir`, recursion depth ≤ `max_depth`; never follow directory symlinks below a root (roots
   themselves may be symlinks); skip hidden names (leading `.`) and names in `exclude_dirs`; ignore
   `PermissionError`. On finding a repo, record it and do not descend unless `descend_into_repos`.
2. Add each `repos` entry that is a repo (else warning), even if hidden or outside the roots.
3. Drop paths matching any `ignore` glob (`fnmatch` against the absolute path, `~` expanded in the glob).
4. Deduplicate by resolved path. Run `rev-parse --absolute-git-dir` per repo (parallel); failures drop
   the repo with a logged warning.
5. Display names: basename; for colliding basenames use `parent/basename`; if still colliding use the
   `~`-abbreviated path. `[repo."<path>"] name = "..."` overrides.
Performance target: under 2 s for a home directory with 50 repos (default `max_depth = 4`).

### 4.6 Configuration (`core/config.py`)
TOML via `tomllib`; the first run writes `default_config.toml` (fully commented, generic roots) to the
platform config path. `Config` is a frozen dataclass; `load(path) -> (Config, list[str] warnings)`.
Unknown keys → warning. Wrong type or out of range → warning and the default for that key. Unparseable
file → keep the previous `Config` (or defaults on startup) and set `config_warning` with the TOML error
line. The scheduler stats the file at every status pass and reloads on mtime change: root/ignore/depth
changes trigger a rescan, interval changes reschedule, `[indicator]` changes re-render.

| Key | Type | Default | Valid |
|---|---|---|---|
| `roots` | list[str] | `["~"]` | — |
| `repos` | list[str] | `[]` | — |
| `ignore` | list[str] | `[]` | globs |
| `max_depth` | int | 4 | 0–12 |
| `descend_into_repos` | bool | false | |
| `exclude_dirs` | list[str] | `node_modules vendor target build dist venv __pycache__ snap Library AppData` | names (hidden dirs are always skipped) |
| `status_interval` | int s | 60 | ≥ 10 |
| `fetch_interval` | int s | 600 | ≥ 60 |
| `rescan_interval` | int s | 600 | ≥ 60 |
| `workers` | int | 4 | 1–32 |
| `fetch_workers` | int | 4 | 1–32 |
| `fetch_timeout` | int s | 60 | 5–600 |
| `action_timeout` | int s | 120 | 10–1800 |
| `count_untracked_as_dirty` | bool | true | |
| `count_no_upstream_as_push` | bool | false | |
| `notifications` | bool | false | |
| `sync_strategy` | str | `"rebase"` | `rebase`, `merge` |
| `terminal` | str | `""` = auto-detect | template with `{path}` |
| `file_manager` | str | `""` = platform default | template with `{path}` |
| `backend` | str | `"auto"` | `auto` or a registered name |
| `panel_theme` | str | `"auto"` | `auto`, `dark`, `light`, `system` |
| `log_level` | str | `"info"` | `debug`, `info`, `warning` |
| `[indicator] label` | list | `["push","pull"]` | ⊆ {push, pull, dirty}, order kept |
| `[indicator] top_dot` | list | `["push"]` | ⊆ {push, pull, dirty} |
| `[indicator] top_dot_color` | str | `"success"` | foreground, warning, error, success, `#rrggbb` |
| `[indicator] bottom_dot` | list | `["pull"]` | as above |
| `[indicator] bottom_dot_color` | str | `"warning"` | as above |
| `[indicator] tint` | list | `[]` | as above |
| `[indicator] tint_color` | str | `"warning"` | warning, error, success, `#rrggbb` |
| `[indicator] glyph_color` | str | `"#e1e1e1"` | `#rrggbb` (hex mode only) |
| `[repo."<path>"] fetch` | bool | true | |
| `[repo."<path>"] name` | str | — | display name override |

Template commands are split with `shlex.split` (POSIX) or `shlex.split(posix=False)` with the
surrounding double quotes removed from each word (Windows: backslashes literal, quoted program paths
with spaces stay whole) **before** substituting `{path}` into each argument; never run through a
shell.

### 4.7 Actions (`core/actions.py`)
All actions take the per-repo lock (blocking, 30 s; else fail with "busy") and run on the fetch pool.
After every action, a status refresh of that repo runs and a snapshot is emitted.

- **Push** (enabled when `ahead > 0`, `behind == 0`, upstream remote ≠ `.`, no operation):
  `push --porcelain <remote> refs/heads/<branch>:<merge>`. Never `--force`, never `-u`, hooks run.
- **Pull** (enabled when `behind > 0`, `ahead == 0`, no operation): `pull --ff-only --no-rebase --quiet`.
- **Sync** (enabled when diverged, no tracked changes, no operation):
  1. `orig = rev-parse HEAD`.
  2. rebase strategy: `pull --rebase --no-autostash --quiet`; merge strategy:
     `pull --no-rebase --no-edit --quiet`.
  3. On failure or timeout: if `rebase-merge/` or `rebase-apply/` exists run `rebase --abort`; if
     `MERGE_HEAD` exists run `merge --abort`. Then compare `rev-parse HEAD` with `orig` and check that
     no operation is in progress: `restored = True` if both hold, otherwise `restored = False` and the
     message says "repository NOT restored — see details" (must never happen; tests prove it).
  4. On success: push exactly as above. A rejected push after a successful rebase reports
     "rebased locally, push rejected: …" with `ok = False`; the local rebase stays (a valid state, the
     next Sync retries).
- **Sync all:** computed from the snapshot at click time: diverged with no tracked changes → sync;
  push-only → push; pull-only → pull; everything else skipped. Runs with `fetch_workers` concurrency;
  `sync_all` progress in the snapshot; one summary result "Synced 4 of 5 · 1 failed · 1 skipped
  (uncommitted changes: notes)".
- **Fetch now (one repo / all):** same as the fetch pass; a manual "fetch all" resets the backoff.
- Commit signing configured by the user may trigger pinentry during a rebase; that is the user's own
  configuration and is documented in troubleshooting, not worked around.

### 4.8 Scheduler (`core/scheduler.py`)
One scheduler thread, two `ThreadPoolExecutor`s (`workers` for status, `fetch_workers` for fetch and
actions), a command queue, and a per-repo `threading.Lock` map. Public API (thread-safe):
`start()`, `stop()`, `refresh_now()`, `fetch_now(path=None)`, `rescan_now()`, `pause_fetching(bool)`,
`run_action(kind, path)`, `sync_all()`, `snapshot()`, `on_snapshot(callback)`. Callbacks run on the
scheduler thread; the app marshals them to the UI thread.

- Startup: scan → status pass → snapshot → first fetch pass 10 s later.
- Status pass every `status_interval`; fetch pass every `fetch_interval` (repos with
  `fetch_enabled = False` skipped; a repo whose lock is held is skipped, not waited for), followed by a
  status pass; rescan every `rescan_interval`.
- Backoff: when every attempted fetch in a pass failed, set `all_fetches_failed` and multiply the next
  delay by 2 up to 3600 s; the first successful fetch resets it. Mode `BACKOFF` while waiting.
- Pause: fetch timer suspended (status continues); mode `PAUSED`.
- Resume from suspend: each loop compares wall-clock and monotonic deltas; a gap > 60 s means the
  machine slept → schedule a fetch pass in 10 s.
- `stop()`: no new work, running git processes killed via the runner, pools shut down within 3 s.
- Clocks and the git runner are injectable for tests.

### 4.9 Presentation models (`core/model.py`, `core/indicator.py`, `core/tooltip.py`)
Pure functions of `(snapshot, config, now)`; no I/O. Definitions on `RepoState`:
`tracked_changes = staged + unstaged + unmerged > 0`; `dirty = tracked_changes or (untracked > 0 and
count_untracked_as_dirty)`; `has_upstream = upstream and not upstream_gone`; `pushable = has_upstream
and ahead > 0 and not detached`; `pullable = has_upstream and behind > 0 and not detached`;
`diverged = pushable and pullable`.

**Counts:** `push` = pushable repos (+ repos without upstream on a branch when
`count_no_upstream_as_push`); `pull` = pullable repos; `dirty` = dirty repos.

**IconSpec** (`indicator.py`): state = `error` if `git_missing or all_fetches_failed`, else `paused`
if fetch paused, else `attention` if any dot or tint triggers, else `clean`. In `attention`, each of
`top_dot`, `bottom_dot`, `tint` is set to its colour when any of its triggers has a non-zero count.
Label = configured parts in order, `↑N` / `↓N` / `✎N`, zero parts omitted, joined by one space; the
label is also shown in error and paused states.

**PanelModel** (`model.py`), frozen dataclasses:

```python
PanelModel(header: Header, columns_title: tuple[str, str], rows: tuple[Row, ...],
           empty_text: str | None, groups: tuple[Group, ...], footer: Footer, banner: Banner | None)
Header(summary: str, fetched_text: str, fetching: bool, paused: bool, warning: str | None)
Row(left: Cell | None, sync: Button | None, right: Cell | None)
Cell(path: Path, name: str, tooltip: str, count_text: str, dirty: bool, warning: str | None, button: Button)
Button(action: ActionKind, enabled: bool, busy: bool, tooltip: str)
Group(kind: str, title: str, icon_name: str, chips: tuple[Chip, ...], collapsed: bool)
Chip(path: Path, name: str, tooltip: str)
Footer(sync_all: Button, label: str)            # label "Sync all" / "Syncing 2/5…"
Banner(kind: str, text: str, result: ActionResult | None, expires_at: float | None)
```

Rules (SPEC §2.5 is the visual reference):
- Rows: diverged repos first as shared rows (left cell, sync button, right cell; their push/pull
  buttons disabled with tooltip "Diverged — use Sync"); then push-only and pull-only lists, each sorted
  by `name.casefold()`, zipped into rows (`left = push[i]`, `right = pull[i]`).
- Button tooltips: "Push 3 commits to origin/main", "Pull 4 commits from origin/main (fast-forward)",
  "Sync: pull --rebase, then push" (merge: "Sync: merge, then push"); disabled reasons "Commit or stash
  first", "Operation in progress: rebase", "Busy: pushing…". While an action runs on a repo, its button
  is `busy` and the repo's other buttons are disabled.
- Header summary: "All N repos in sync" / "N repos need attention" / "Fetching…" / "Offline — fetch
  failed for every repo, retrying in 8 min" / "Fetching paused". `fetched_text` "Fetched 3 min ago",
  "Fetched just now", "Never fetched".
- Groups in order, each omitted when empty: `✎ Uncommitted` (all dirty repos), `⚠ No upstream`
  (incl. upstream gone, tooltip says which), `Detached`, `⚠ In progress` (operation set), `⚠ Fetch
  failed` (tooltip: the error), `In sync` (collapsed).
- Banner: the newest result younger than 6 s (success) or the newest unacknowledged failure; failures
  persist until the panel is closed.
- `empty_text = "Nothing to push or pull"` when there are no rows.
- `menus.py`-independent menu models (`MenuItem(label, action, enabled, checked, children,
  separator)`) for: the secondary/control menu, the gear menu (same items), the per-repo context menu,
  and the full fallback menu for `caps.panel = False` backends (SPEC §2.3).

**Tooltip** (`tooltip.py`): SPEC §2.2 layout, max 15 repo lines then "… and N more". Markup variant
escapes names with `html.escape` and bolds group titles; plain variant otherwise; when
`tooltip_max_chars` is set, a single summary line `repotray: ↑2 ↓1 ✎3 · fetched 3 min ago` truncated to
the limit.

### 4.10 Platform services (`platform/`)
```python
class Platform(Protocol):
    name: str                                   # "linux" | "macos" | "windows"
    def config_dir(self) -> Path: ...
    def state_dir(self) -> Path: ...            # logs
    def cache_dir(self) -> Path: ...            # hex-mode icons
    def runtime_dir(self) -> Path: ...          # lock file
    def git_env(self) -> dict[str, str]: ...
    def popen_kwargs(self) -> dict: ...
    def kill_tree(self, proc: subprocess.Popen) -> None: ...
    def acquire_instance_lock(self, path: Path) -> InstanceLock | None: ...   # None = already held; writes pid
    def open_terminal(self, path: Path, template: str) -> None: ...
    def open_folder(self, path: Path, template: str) -> None: ...
    def open_file(self, path: Path) -> None: ...      # config file in the default editor
    def notify(self, title: str, body: str) -> bool: ...   # fallback when the backend cannot
    def autostart_enable(self, argv: list[str]) -> str: ...  # returns where it wrote
    def autostart_disable(self) -> None: ...
    def autostart_enabled(self) -> bool: ...
    def install_icons(self, src: Path) -> list[Path]: ...    # no-op returning [] off Linux
    def uninstall_icons(self) -> list[Path]: ...
    def desktop_info(self) -> dict[str, str]: ...            # for `doctor`
    def prefers_dark_panel(self) -> bool | None: ...
```
- **Linux:** XDG dirs (`~/.config`, `~/.local/state`, `~/.cache`, `$XDG_RUNTIME_DIR` falling back to
  state dir). Lock via `fcntl.flock`. Terminal auto-detect in order: `x-terminal-emulator` target if it
  resolves to a known one, then gnome-terminal / terminator / xfce4-terminal / mate-terminal
  (`--working-directory={path}`), konsole (`--workdir {path}`), tilix (`-w {path}`), kitty
  (`--directory {path}`), alacritty (`--working-directory {path}`), wezterm (`start --cwd {path}`),
  foot (`-D {path}`), xterm; always also `cwd=path`. Folder: `xdg-open`. Notify fallback:
  `notify-send`. Autostart: `~/.config/autostart/repotray.desktop` (`Exec=` the absolute argv,
  `X-GNOME-Autostart-enabled=true`, `NoDisplay=true`). Icons: copy `icons/data/symbolic/*.svg` to
  `$XDG_DATA_HOME/icons/hicolor/scalable/status/` when missing or different; record copied files in
  `$XDG_DATA_HOME/repotray/icons.manifest`; skip if `/usr/share/icons/hicolor/scalable/status/repotray-symbolic.svg`
  exists. Desktop info: `XDG_CURRENT_DESKTOP`, `XDG_SESSION_TYPE`, Cinnamon/GTK theme names via
  `gsettings` (subprocess, tolerate absence).
- **macOS:** `~/Library/Application Support/repotray`, `~/Library/Caches/repotray`; lock `fcntl`;
  terminal `open -a Terminal {path}`; folder `open`; notify `osascript -e 'display notification …'`;
  autostart `~/Library/LaunchAgents/io.github.repotray.plist` via `plistlib` (`RunAtLoad`).
  Dark menu bar: `defaults read -g AppleInterfaceStyle`.
- **Windows:** `%APPDATA%\repotray` config, `%LOCALAPPDATA%\repotray` state/cache/runtime; lock via
  `msvcrt.locking`; terminal `wt -d {path}` else `cmd /K cd /d {path}`; folder `explorer {path}`;
  autostart Run key with `pythonw.exe -m repotray`; light taskbar via
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\SystemUsesLightTheme`.
- macOS and Windows modules are written to the same standard, unit-tested with mocks, and marked
  untested on real systems in README and docs/porting.md.

### 4.11 Backends, registry, demo (`backends/`, `core/demo.py`)
```python
class Capabilities(TypedDict):
    tooltip: bool; tooltip_markup: bool; tooltip_max_chars: int | None
    label: bool; panel: bool; two_menus: bool; notifications: bool; anchor: bool

class TrayBackend(Protocol):
    name: ClassVar[str]
    caps: Capabilities
    @classmethod
    def probe(cls, platform: Platform) -> ProbeResult: ...   # ProbeResult(score: int, reason: str)
    def __init__(self, platform: Platform, controller: Controller) -> None: ...
    def set_icon(self, icon: IconSpec) -> None: ...
    def set_label(self, text: str) -> None: ...
    def set_tooltip(self, text: str) -> None: ...
    def set_menus(self, control: list[MenuItem], fallback: list[MenuItem] | None) -> None: ...
    def show_panel_model(self, model: PanelModel) -> None: ...   # no-op unless caps.panel
    def notify(self, title: str, body: str) -> None: ...
    def copy_to_clipboard(self, text: str) -> None: ...
    def call_soon(self, fn: Callable[[], None]) -> None: ...     # thread-safe; runs fn on the UI thread
    def run(self) -> None: ...                                    # blocks until quit()
    def quit(self) -> None: ...
```

**Controller** (`app.py`) is the only thing UIs call: `fetch_all()`, `fetch(path)`, `push(path)`,
`pull(path)`, `sync(path)`, `sync_all()`, `set_paused(bool)`, `rescan()`, `open_config()`,
`open_terminal(path)`, `open_folder(path)`, `copy_path(path)`, `set_autostart(bool)`,
`autostart_enabled()`, `about()`, `acknowledge_banner()`, `quit()`. The controller subscribes to
scheduler snapshots, builds IconSpec/label/tooltip/PanelModel/menus, and pushes them through
`backend.call_soon`. With `--demo` it uses `DemoScheduler` (same API) instead of the real scheduler.

**Registry** (`registry.py`): built-ins as lazy import strings (`"xapp": "repotray.backends.xapp:XAppBackend"`,
`appindicator`, `gtkstatusicon`, `qt`, `pystray`, `fake`) plus third-party classes from
`importlib.metadata.entry_points(group="repotray.backends")`. Selection: `--backend` >
`REPOTRAY_BACKEND` > config `backend` > highest probe score > 0. Import errors yield score 0 with the
exception as reason. `repotray doctor` prints every backend with score and reason.

| Backend | Probe | Caps |
|---|---|---|
| `xapp` | Linux; `gi.require_version("XApp","1.0")` works and a bus name starting with `org.x.StatusIconMonitor.` exists → 100; XApp importable but no monitor → 30 (libxapp falls back on its own; confirm via doctor) | tooltip markup, label, panel, two menus, notifications (Notify 0.7), anchor |
| `appindicator` | Linux; AyatanaAppIndicator3 0.1 (or AppIndicator3 0.1) importable and `org.kde.StatusNotifierWatcher` on the bus → 80 | label, panel (opened from a menu item / middle click, at the pointer), notifications; no tooltip, no anchor |
| `gtkstatusicon` | Linux, X11 session → 20 | tooltip markup, panel, two menus, anchor via `get_geometry()`; no label |
| `qt` | `PySide6` importable → 70 on Windows, 40 on macOS (untested), 5 on Linux | plain tooltip (127 chars on Windows), panel, two menus, notifications, anchor via `QSystemTrayIcon.geometry()`; no label |
| `pystray` | `pystray` and `PIL` importable → 50 on macOS/Windows, 10 on Linux | plain tooltip (127 chars on Windows), one menu, no panel, no label |
| `fake` | never auto-selected; `--backend fake` | configurable; records every call; for tests and headless runs |

**XApp specifics:** `set_name("repotray")`; icon name from `icons/names.py`, or the hex-mode SVG path;
`set_tooltip_text(markup)`; `set_secondary_menu(Gtk.Menu)`; **no primary menu**. Connect
`button-release-event(x, y, button, time, position)`: button 1 → `panel.toggle(Anchor(x, y, side))` with
side from `Gtk.PositionType` (0 left, 1 right, 2 top, 3 bottom); button 2 → `controller.fetch_all()`.
Ignore `activate` (it fires on the same click).

**AppIndicator specifics:** menu = fallback menu prefixed by "Open panel…"; `secondary-activate`
(middle click) opens the panel at the pointer; label via `set_label`; hex icons via
`set_icon_theme_path(cache_dir)` and a name without "symbolic".

**Qt specifics:** `QSystemTrayIcon.activated`: `Trigger` (left) → `panel.toggle(anchor)` with the anchor
from the icon rectangle (`ui/placement.anchor_from_icon`, shared with `gtkstatusicon`), `MiddleClick` →
fetch all, `Context` → the control menu set with `setContextMenu`. `call_soon` emits a signal with a
queued connection to an object on the Qt thread. Tray icon = one pixmap per size 16–64 px from
`icons/raster.py`. The panel (`ui/qt/panel.py`) mirrors the GTK one widget for widget; dialogs in
`ui/qt/dialogs.py`; texts shared through `ui/text.py`.

**pystray specifics:** run with `icon.run(setup)`; `call_soon` enqueues and the queue is drained by a
worker that applies updates under a lock and calls `icon.update_menu()`. Icon images from
`icons/raster.py` at 64 px (macOS: black glyph for a light menu bar, white for dark; Windows: per
SystemUsesLightTheme). Marked experimental.

**Demo** (`core/demo.py`): repos `api-gateway` (↑3, dirty), `infra` (↑1), `website` (↓4),
`design-system` (↑2 ↓2 diverged), `mobile-app` (↓2), `notes` (dirty only), `scratch` (dirty, no
upstream), `experiments` (no upstream), `docs` and `dotfiles` (clean), `legacy-tools` (fetch failed:
"Could not resolve host"). Simulated actions take 1.5 s; `mobile-app` pull fails with a realistic
"Not possible to fast-forward" error; all others succeed and update the demo state.

### 4.12 Icons (`tools/build_icons.py`, `icons/`)
**Glyph source:** `tools/octicons/repo-16.svg` — download verbatim from
`https://raw.githubusercontent.com/primer/octicons/main/icons/repo-16.svg` together with
`https://raw.githubusercontent.com/primer/octicons/main/LICENSE`. If offline, use this path (fetched
2026-10-05) and the standard MIT text with "Copyright (c) GitHub Inc.", and note it in decisions:

```
M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z
```

**Build** (this exact approach produced a correct result in the live tray): parse with `svgpathtools`,
flatten every segment at ≤ 0.05 units, turn each subpath into a shapely `Polygon(...).buffer(0)`, combine
subpaths with `symmetric_difference` (even-odd), apply the glyph transform (scale 1.0 about (8,8),
offset 0; constants at the top of the script), and subtract `Point(13,3).buffer(4)` /
`Point(13,13).buffer(4)` for each shown dot. Simplify with tolerance 0.01, round to 3 decimals, emit
`<path fill-rule="evenodd" …>` with `M … L … Z` rings. Never use masks or clip paths: symbolic loaders
recolour every element.

**Outputs** (committed; a test regenerates into tmp and diffs):
- `repotray[-tint-<t>][-top-<c>][-bottom-<c>]-symbolic.svg` for tint ∈ {none, warning, error,
  success} and each dot ∈ {none, foreground, warning, error, success}: 100 files. Glyph path gets
  `class="<t>"` and the matching fallback fill when tinted, else `fill:#bebebe`. Dots are
  `<circle cx="13" cy="3|13" r="3">` with `class="<c>"` and fallback fill (`#f57900` warning, `#e01b24`
  error, `#2ec27e` success); foreground dots have no class and fill `#bebebe`.
- `repotray-error-symbolic.svg`: glyph knocked out bottom-right, an × inside the r=3 circle at (13,13)
  (two 1.5-wide, 5-long bars at ±45°) with `class="error"`.
- `repotray-paused-symbolic.svg`: glyph knocked out bottom-right, two foreground bars x 11.0–12.25 and
  13.75–15.0, y 10.5–15.5.
- `geometry.json`: rings for glyph variants `none|top|bottom|both`, dot circles, cross, bars — the input
  for `icons/svg.py` (hex mode) and `icons/raster.py` (Pillow, drawn at 4× and downsampled with LANCZOS).
- 16×16 viewBox, `width="16" height="16"`, no metadata, each file < 4 KB.

`icons/names.py`: `IconSpec → "repotray-tint-warning-top-success-symbolic"` etc. Hex mode: any `#rrggbb`
colour switches the whole icon to `icons/svg.py`, written to `cache_dir/icon-<sha1[:12]>.svg`; the
filename never contains "symbolic"; untinted parts use `glyph_color`.

### 4.13 GTK 3 panel (`ui/gtk3/`, `ui/placement.py`)
- **Window:** `Gtk.Window(type=TOPLEVEL)`, `decorated=False`, `skip_taskbar_hint`, `skip_pager_hint`,
  `keep_above`, `resizable=False`, type hint `UTILITY`; if focus-out does not fire reliably on Muffin,
  try `DIALOG` and record the result in decisions. Width 480 logical px, scrolled rows area capped at
  12 rows (`propagate_natural_height`).
- **Structure** (top to bottom): header box (summary label, dim "Fetched …" label, flat icon button
  `view-refresh-symbolic` replaced by a `Gtk.Spinner` while fetching); `Gtk.InfoBar` banner with a
  "Details…" button; separator; column titles `Push (N)` / `Pull (N)` (bold); a `Gtk.Grid` with seven
  columns `name | counts | push | sync | pull | counts | name`, right column right-aligned so the
  buttons meet in the middle; empty-state label; separator; groups (`Gtk.FlowBox` of flat chip buttons;
  `In sync` inside a `Gtk.Expander`); separator; footer with "Sync all" (`suggested-action`,
  `emblem-synchronizing-symbolic`) and a gear `Gtk.MenuButton` (`emblem-system-symbolic`).
- Repo names are flat buttons (ellipsize middle, ≤ 24 chars) opening the repo context menu; action
  buttons use the icon names from SPEC §6 at 16 px, and busy buttons swap their image for a spinner.
- **Theme:** `theme.py` applies `panel_theme` (§1) and a small CSS provider (padding, dim labels,
  tabular numbers). No hard-coded colours.
- **Show/hide:** `toggle(anchor)`; position from `placement.place(anchor, size, workarea) -> (x, y)`:
  bottom panel → centred on `anchor.x + 12`, bottom edge on the workarea bottom; top → top edge on
  workarea top; left/right analogous; always clamped inside the workarea of the monitor containing the
  anchor (`Gdk.Display.get_monitor_at_point(...).get_workarea()`). No anchor → at the pointer, clamped.
  Re-place on size changes. `present_with_time(time)` then focus the GdkWindow.
- **Closing:** Escape, focus-out, second click. While a child menu or the details dialog is open,
  focus-out is ignored (track menu `show`/`deactivate`). **Reopen race:** a click on the tray icon first
  makes the panel lose focus (hide) and then delivers the release (toggle → show again). Ignore a
  toggle-to-show within 300 ms after a focus-out hide.
- **Updates:** `show_panel_model` diffs against the previous model and rebuilds only changed rows; the
  "Fetched …" text refreshes every 30 s while visible.
- **Details dialog:** transient for the panel, monospace `Gtk.TextView` with command, exit status and
  full output, "Copy" and "Close" buttons.

### 4.14 App, CLI, logging
**CLI** (`repotray <command>`; global `--config PATH`, `-v/--verbose`, `--backend NAME`, `--version`):

| Command | Behaviour | Exit |
|---|---|---|
| *(none)* / `tray [--demo]` | start the tray | 0 |
| `status [--json] [--demo]` | scan + one status pass, table or JSON | 0; 2 config error |
| `scan [--absolute]` | discovered repos, one per line (`~`-abbreviated) | 0 |
| `fetch [REPO…]` | fetch pass (all or given) + status table | 0; 1 if any failed |
| `push REPO…` / `pull REPO…` | actions; REPO = display name, basename or path; ambiguous → candidates listed | 0; 1 failed; 2 usage |
| `sync [--all \| REPO…]` | per repo: push if ahead only, pull if behind only, sync if diverged | as above |
| `doctor` | version, Python, platform + desktop info, git version, config path + warnings, roots + repo count, backend table, icon install status | 0 |
| `config path` / `config default` | print path / print default config | 0 |
| `autostart enable\|disable\|status` | via platform | 0 |
| `icons install\|uninstall` | via platform (tray installs at startup anyway) | 0 |
| `quit` | SIGTERM to the pid in the instance lock (POSIX); Windows: not supported message | 0; 1 none running |

Status table columns `NAME BRANCH ↑ ↓ STATE PATH`, STATE a comma list (`push`, `pull`, `diverged`,
`dirty`, `no upstream`, `detached`, `fetch failed`, `rebase`…). JSON (documented in docs/cli.md):
`{"version": 1, "generated_at": ISO-8601, "counts": {push, pull, dirty, diverged, no_upstream, detached,
fetch_failed, total}, "repos": [{path, name, branch, upstream, ahead, behind, staged, unstaged,
untracked, unmerged, dirty, detached, no_upstream, upstream_gone, operation, fetch_error,
status_error}]}`.

**Tray startup:** load config (write the default on first run) → instance lock → `install_icons` (Linux)
→ select backend → controller + scheduler → `backend.run()`. SIGINT/SIGTERM quit cleanly (GTK backends
via `GLib.unix_signal_add`). Unhandled exceptions in callbacks are logged, never crash the tray.

**Logging:** stdlib `logging`. Tray: rotating file `state_dir/repotray.log` (1 MB × 3) plus stderr with
`-v`. CLI: stderr only. Never log credentials or full remote URLs containing user info (strip
`user:pass@`).

---

## 5. Milestones

Each milestone lists deliverables, then acceptance checks that must all pass before committing.

### M0 — Skeleton
- The git repo already exists (branch `main`, remote `origin` =
  `https://github.com/ymihere/repotray`, private) with a first commit containing SPEC.md, PLAN.md,
  CLAUDE.md and a minimal `.gitignore`. Extend `.gitignore` as needed (`.venv/`, `__pycache__/`,
  `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `HANDOFF.md`,
  `CLAUDE.local.md`, `.tmp*/`) and confirm with `git status --ignored` that CLAUDE.local.md stays
  ignored. Commit locally only; the maintainer pushes.
- `pyproject.toml`: hatchling; `requires-python = ">=3.11"`; `dependencies = ["pystray>=0.19;
  sys_platform == 'darwin' or sys_platform == 'win32'", "Pillow>=9; sys_platform == 'darwin' or
  sys_platform == 'win32'"]` (since 2026-10-07: `PySide6-Essentials>=6.8` instead of pystray on
  Windows, extra `qt`, and a `repotrayw` gui-script); extras `dev = ["pytest>=8", "ruff>=0.6", "shapely>=2", "svgpathtools>=1.6",
  "build", "twine"]`, `pystray = ["pystray>=0.19", "Pillow>=9"]`; `[project.scripts] repotray =
  "repotray.cli:main"`; package data includes `icons/data/**` and `default_config.toml`; classifiers;
  URLs (§1); ruff (line length 100, rules E F W I UP B SIM); pytest markers `integration`, `gui`,
  `conformance`; `gui` tests skipped unless `REPOTRAY_GUI_TESTS=1`.
- `scripts/dev-setup.sh` (§2), package skeleton, `__main__.py`, `cli.py` with `--version`.
- **Accept:** `dev-setup.sh` succeeds twice in a row; `python -m repotray --version` prints `0.1.0`;
  `pytest -q` and ruff run clean.

### M1 — Headless core and CLI
- Everything under `core/` and `platform/`, `default_config.toml`, `cli.py` (all commands of §4.14
  except `tray`), the fake backend is not needed yet.
- Tests (unit): porcelain parser with byte fixtures for clean, staged, unstaged, untracked-only,
  unmerged, ahead, behind, diverged, no upstream, upstream gone, detached, initial commit, a rename whose
  original path starts with `1 ` and one starting with `? `; scanner (depth limit, exclusions, hidden
  dirs pruned but hidden root and hidden `repos` entry scanned, nested repos with
  `descend_into_repos` false/true, `.git` file worktree, bare repo ignored, symlink loop, ignore globs,
  name collisions); config (defaults, every validation rule, unknown keys, parse error keeps previous,
  reload on mtime); model/indicator/tooltip (row allocation, button rules, groups, banner timing,
  label composition, dot/tint triggers, `count_no_upstream_as_push`, error > paused > attention,
  tooltip cap and 127-char mode, markup escaping); scheduler with fake runner and fake clocks (pass
  timing, skip locked repos, backoff doubling and reset, pause, resume detection, stop kills); layering.
- Tests (integration, real git in `tmp_path`): a bare remote + two clones; status JSON for ahead,
  behind, diverged, dirty; push clears ahead; pull clears behind; sync on diverged rebases and pushes;
  sync with a conflicting edit aborts with `restored=True` and identical HEAD, index (`git status
  --porcelain=v2` output) and file contents; sync refused with tracked changes without running git;
  sync with only untracked files proceeds; merge strategy produces a merge commit without an editor;
  timeout: a TCP server that accepts and never answers as the remote, `action_timeout=3` → killed within
  6 s, repo unchanged; no prompting: an HTTP server answering 401 as the remote → fetch fails within
  10 s with stdin closed and no hang; `ssh://` to a closed local port fails fast; CLI commands run as
  subprocesses against a fixture config, exit codes as in §4.14.
- **Accept:** all tests green. On the dev machine, with a temporary config listing the real roots (see
  CLAUDE.local.md): `repotray scan` finds exactly the expected repos in < 2 s, and `repotray status`
  finishes in < 3 s with ahead/behind/dirty matching a scripted
  `git status --porcelain=v2 --branch` loop over the same repos. `repotray status --demo --json`
  matches the documented schema.

### M2 — Icons
- `tools/octicons/*`, `tools/build_icons.py`, `icons/data/*` (generated, committed), `icons/names.py`,
  `icons/svg.py`, `icons/raster.py`, `scripts/dev/preview-icons.py`.
- Tests: all 102 files exist and parse; dots present exactly where the name says; no glyph vertex
  inside a shown dot's radius-3.9 disc; regenerated output equals the committed files (skipped without
  shapely); names for every IconSpec; hex SVG filename never contains "symbolic"; raster output size
  and alpha at dot centres.
- **Accept, visual:** `preview-icons.py` renders a contact sheet of all variants at 16, 24 and 32 px on
  a dark (#303036, fg #e1e1e1) and a light (#f6f6f6, fg #2e3436) background via GTK `load_symbolic`;
  read the PNG: the book is recognisable in every variant, dots are round and separated by a visible
  transparent ring. **Accept, live:** `repotray icons install`, show plain, top, bottom, both, error,
  paused and tint-warning in the tray for 5 s with a throwaway XApp script, screenshot, read it; the
  bottom dot matches the mintupdate shield's dot in size and position. Then kill the script. Keep the
  icons installed (the tray needs them; M6 uninstall/install cycles cover cleanup).

### M3 — Cinnamon backend and panel
- `backends/base.py`, `registry.py`, `fake.py`, `xapp.py`; `ui/placement.py`; `ui/gtk3/*`; `app.py`;
  `cli tray`; `scripts/dev/screenshot.py` (captures the tray strip or a window rectangle, scales ×3),
  `scripts/dev/click-tray.sh BUTTON` (finds the `org.x.StatusIcon.*repotray*` bus name and calls
  `ButtonRelease` with the icon position; see CLAUDE.local.md for the exact call).
- Tests: placement (all four sides, clamping, multi-monitor offsets); conformance suite
  `tests/conformance/` parametrised by `REPOTRAY_BACKEND` (default `fake`): every IconSpec, label,
  tooltip, nested menus, `call_soon` from another thread runs on the UI thread, `quit()` makes `run()`
  return within 2 s; GUI tests (`REPOTRAY_GUI_TESTS=1`): panel built from the demo model has the
  expected rows and button states, clicking a demo push button shows the spinner and then the success
  banner, Escape hides, a focus-stealing helper window hides it, the 300 ms reopen guard works.
- **Accept, live** (all with `--demo`, never with real repos):
  1. `repotray tray --demo &`; after 3 s a tray screenshot shows the repotray icon with both dots and
     the label `↑3 ↓3` (push: api-gateway, infra, design-system; pull: website, design-system,
     mobile-app).
  2. `click-tray.sh 1` → screenshot: the panel is above the icon, inside the monitor, dark, and its
     layout matches SPEC §2.5 (columns mirrored, sync button in the gutter for `design-system`,
     groups, footer). Iterate on spacing until it looks native next to Cinnamon's own popups.
  3. `click-tray.sh 1` again → panel hidden. `click-tray.sh 2` → header spinner (fetching).
     `click-tray.sh 3` → control menu screenshot.
  4. `repotray tray` (second instance) prints "already running" and exits 0. `repotray quit` stops
     the first; no processes remain (`pgrep -f "repotray"` empty).

### M4 — Other backends and platforms
- `appindicator.py`, `gtkstatusicon.py`, `pystray_backend.py`; complete `platform/macos.py` and
  `platform/windows.py`.
- Tests: platform unit tests with mocks (paths, terminal argv, autostart files/registry calls via a
  fake `winreg`, notify fallback commands); pystray backend tests skip if pystray is missing; conformance
  suite against every backend that imports on this machine.
- **Accept, live on the dev machine** (install pystray into the venv): run `--demo` with
  `--backend appindicator`, `--backend gtkstatusicon` and `--backend pystray` in turn, screenshot the
  tray and open the menu/panel where a click can be simulated; record in `docs/decisions.md` which ones
  display on Cinnamon and how. `repotray doctor` lists all backends with sensible scores and picks
  `xapp`.

### M5 — Docs, scripts, CI, packaging
- **README.md:** one-paragraph pitch; demo screenshots (tray crop, panel); features; install (Cinnamon
  recommended: `scripts/install.sh`; other Linux: same plus `gir1.2-ayatanaappindicator3-0.1`;
  pipx: `pipx install --system-site-packages repotray`; macOS/Windows: `pip install repotray`,
  experimental); usage (left/middle/right click, panel, Sync semantics); configuration summary linking
  docs/configuration.md; CLI summary; safety guarantees (never force, never prompts, aborts on conflict,
  status never writes); platform support matrix (tested / expected to work / experimental / help
  wanted); contributing and porting links; credits (Octicons MIT); licence.
- **docs/:** configuration.md (every key from §4.6 with examples, incl. the three `[indicator]`
  recipes from SPEC §5), cli.md (commands, exit codes, JSON schema), architecture.md (layers, threads,
  data flow diagram in text), porting.md (Platform and TrayBackend protocols, registry and entry points
  with a complete minimal example backend package, capabilities contract, using `--demo` and
  `--backend fake`, running the conformance suite, what a platform report must contain),
  troubleshooting.md (icon not shown, prompts, GPG pinentry, Wayland: no panel positioning), decisions.md.
- **CONTRIBUTING.md** (dev setup, tests and markers, lint, GUI verification tools, commit style, PR
  checklist), **CODE_OF_CONDUCT.md** (short; adopts Contributor Covenant 2.1 by link), **SECURITY.md**
  (private reporting via GitHub security advisories; the safety model), **CHANGELOG.md** (Keep a
  Changelog, `0.1.0 — unreleased`), **RELEASING.md** (push, make the GitHub repo public, configure
  PyPI trusted publishing, tag `v0.1.0`; maintainer-only steps), **LICENSE**.
- **.github/:** issue forms (bug report asks for `repotray doctor` output; platform report asks for OS,
  desktop, backend, screenshots, conformance results), PR template, `ci.yml` (ruff + pytest on
  ubuntu-latest Python 3.11/3.12/3.13, macos-latest and windows-latest Python 3.12; GUI tests off),
  `release.yml` (on tag `v*`: build sdist + wheel, publish with `pypa/gh-action-pypi-publish` using
  trusted publishing).
- **scripts/install.sh** (Linux, no pip needed): checks Python ≥ 3.11 and gi with XApp or AppIndicator
  (prints the apt package names if missing, never runs sudo); copies `src/repotray` to
  `~/.local/share/repotray/lib/`; writes `~/.local/bin/repotray` (`#!/bin/sh` launcher setting
  `PYTHONPATH` and exec'ing `/usr/bin/env python3 -m repotray "$@"`); installs icons; writes
  `~/.local/share/applications/repotray.desktop`; records everything in
  `~/.local/share/repotray/install-manifest.txt`; `--autostart` enables autostart; starts the tray
  detached unless `--no-start`; idempotent (re-run = upgrade, restarting a running instance).
  **scripts/uninstall.sh:** `repotray quit`, autostart disable, icons uninstall, remove manifest files;
  keeps the config unless `--purge`.
- Packaging: `python -m build` → sdist + wheel; `twine check dist/*`; install the wheel into a fresh
  `--system-site-packages` venv in a temp dir and run `repotray doctor` and `repotray status --demo`.
- Docs tests: every config key appears in docs/configuration.md; every CLI command appears in README
  and docs/cli.md; every relative link in Markdown files resolves.
- **Accept:** docs tests green; `bash -n` and `shellcheck` (if available) clean on scripts;
  install.sh → uninstall.sh round trip into a temporary `HOME` leaves nothing behind (diff the
  directory tree before/after); CI YAML parses (`python -c "import yaml"` if available, else review);
  the wheel contains all 102 SVGs, geometry.json, LICENSE-octicons and default_config.toml.

### M6 — Final acceptance and hand-off
1. Fresh clone of the repo into a temporary directory; `scripts/dev-setup.sh`; full suite including
   `REPOTRAY_GUI_TESTS=1`; ruff clean.
2. Privacy sweep over tracked files: no real repo names or private paths (CLAUDE.local.md lists what
   is private), no email addresses except in LICENSE/pyproject if deliberately added, screenshots only
   from `--demo`.
3. Install for the maintainer: `scripts/install.sh` **without** `--autostart`. If no config exists,
   create it with the real roots from CLAUDE.local.md. Leave exactly one tray instance running.
   Screenshot the tray to confirm the icon and label appear; do not open the panel on real repos and do
   not trigger actions. Save `repotray doctor` output.
4. Write `HANDOFF.md` (gitignored): what was built per milestone; test summary (counts, runtime);
   verified vs. unverified (macOS, Windows, CI never run on GitHub, PyPI not published, real-click
   behaviour only simulated over D-Bus); open items from docs/decisions.md; the SPEC §9 manual checklist
   for the maintainer; how to publish (RELEASING.md); how to uninstall; the doctor output.
5. Update CLAUDE.md "Status", SPEC.md where implementation changed behaviour, CHANGELOG; final commit
   `M6: release candidate 0.1.0`. Do not tag, do not push.

---

## 6. Definition of done
- [ ] Every SPEC.md behaviour implemented or listed as deliberately deferred in docs/decisions.md.
- [ ] All tests green on the dev machine, including GUI tests; ruff clean.
- [ ] Panel, tray icon, dots, label and menus verified by screenshot on Cinnamon (`--demo`).
- [ ] No GUI import reachable from `core/`, `platform/`, `cli status`.
- [ ] A new backend can be added as a separate package via the `repotray.backends` entry point,
      demonstrated by the example in docs/porting.md and a test that registers a dummy entry point.
- [ ] README, docs, CONTRIBUTING, SECURITY, CHANGELOG, RELEASING, LICENSE, issue/PR templates, CI and
      release workflows present and consistent with the code.
- [ ] install.sh / uninstall.sh round trip clean; wheel builds and installs.
- [ ] No private data in tracked files; nothing pushed or published; one installed tray instance
      running; HANDOFF.md written.
