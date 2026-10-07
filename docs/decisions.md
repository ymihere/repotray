# Decisions log

Choices made during implementation where SPEC.md / PLAN.md left room. Newest last.
Format: date — question → choice (reason).

## Decisions

- 2026-10-07 — ruff ≥ 0.15 formats Python blocks inside Markdown, which would rewrite the
  illustrative code in SPEC/PLAN → `[tool.ruff.format] exclude = ["*.md"]` (those blocks are
  documentation, not source).
- 2026-10-07 — `ActionResult.command` holds several git calls for one action (sync = pull, abort,
  push) → one string per git command line, credentials stripped (the details dialog prints them one
  per line).
- 2026-10-07 — `ActionResult` gained `name` (display name) so results render without a lookup.
- 2026-10-07 — Every action re-reads the repo status under the repo lock and re-checks its
  preconditions before running git (the click may be based on a stale snapshot). Refusals carry
  the panel's tooltip text ("Commit or stash first", "Diverged — use Sync").
- 2026-10-07 — After an action timeout, a stale `index.lock` is removed only when its mtime is not
  older than the action's start (so it was ours), then a half-done rebase/merge is aborted.
- 2026-10-07 — git runs with `LC_ALL=C` so messages shown in the UI and the conflict detection do
  not depend on the user's locale.
- 2026-10-07 — Repos whose `git status` fails get their own panel group "Unreadable (N)" next to
  "Fetch failed"; they are never counted as in sync.
- 2026-10-07 — `Scheduler.on_result(cb)` added beside `on_snapshot` so the controller learns about
  finished actions without diffing snapshots (used for notifications when the panel is closed).
- 2026-10-07 — Scheduler commands are processed before timers in each loop step, so e.g. a
  "pause" issued just before a due fetch wins.
- 2026-10-07 — macOS state dir is `~/Library/Logs/repotray` (logs live there); Windows cache dir is
  `%LOCALAPPDATA%\repotray\cache`.
- 2026-10-07 — Octicons fetched online (repo-16.svg identical to the path in PLAN §4.12; LICENSE
  says "Copyright (c) 2026 GitHub Inc.", copied verbatim).
- 2026-10-07 — Dot circles in the build use `quad_segs=32` for the r=4 knockout (128-gon), so every
  glyph vertex stays ≥ 3.99 from a dot centre.
- 2026-10-07 — `scripts/dev/preview-icons.py` uses Adwaita-like theme colours (success #33d17a,
  warning #f27835, error #e01b24) for the preview; real panels use their own.
- 2026-10-07 — Panel window: type hint `UTILITY` worked on Muffin (focus-out fires; GUI test
  `test_focus_loss_hides` passes), so `DIALOG` was not needed. The window is also made sticky.
- 2026-10-07 — The panel view rebuilds per section (header, banner, rows, groups, footer) when that
  section's model changed, not per row: rows are cheap and a changed row usually swaps a button for
  a spinner anyway.
- 2026-10-07 — Disabled action buttons are wrapped in an EventBox so their reason tooltip
  ("Diverged — use Sync", "Commit or stash first") still shows; GTK hides tooltips of insensitive
  widgets.
- 2026-10-07 — The scroller's min content height is pinned to min(rows, 12 rows): undecorated
  toplevels were allocated only the scroller's minimum height (one row).
- 2026-10-07 — Controller gained `dispatch(action, path)` (menu/panel actions by name), `refresh()`
  (re-render for relative times and banner expiry, ticked every 2 s while the panel is open),
  `panel_opened()` / `panel_closed()` (closing acknowledges failure banners).
- 2026-10-07 — While Sync all runs, per-repo results are not notified; only the summary is.
- 2026-10-07 — libxapp crashes (SIGSEGV in the main loop) when an `XApp.StatusIcon` is finalised
  right after creation. The tray never disposes its icon; the conformance tests keep backends alive.
- 2026-10-07 — `scripts/dev/render-panel.py` renders the panel offscreen from the demo snapshot in
  several states (used while the screen was locked, and for doc screenshots).
- 2026-10-07 — The instance lock file is never unlinked on exit (unlinking races a starting
  instance); `repotray quit` checks that the lock is actually held before trusting the pid.
- 2026-10-07 — M4 live results on Linux Mint 22.3 Cinnamon (X11), all with `--demo`:
  - `xapp` (score 100, auto-selected): icon, label, markup tooltip, panel, control menu — M3 checks.
  - `appindicator` (80): shown through `xapp-sn-watcher` as an XApp icon with both dots; **no
    label** (the watcher does not forward SNI labels). A simulated left click on the watcher's proxy
    object opened the fallback menu (Open panel…, Sync/Push/Pull items, groups, Sync all, control
    items).
  - `gtkstatusicon` (20): shown in the XEmbed area at 24 px with both dots (a `Gdk-CRITICAL`
    thaw warning is printed by GTK at startup; harmless). Click not simulated (no D-Bus hook;
    real mouse clicks were not used to avoid moving the maintainer's pointer).
  - `pystray` (10): shown via pystray's own AppIndicator path as a full-colour 64 px raster. Click
    not simulated.
- 2026-10-07 — pystray: no default menu item, so on Windows the left click does nothing and the
  right click opens the menu; macOS status-item titles (counts next to the icon) are not reachable
  through pystray, so counts live in the tooltip and menu there. Both are porting opportunities.
- 2026-10-07 — pystray's "UI thread" is the backend's queue worker (`backend.ui_thread`); the
  conformance suite accepts a backend-declared UI thread.
- 2026-10-07 — `gtkstatusicon` anchors the panel from `get_geometry()`: bottom/top/left/right is
  inferred from where the icon sits on its monitor.
- 2026-10-07 — CI on Windows skips the real-git integration tests and the symlink/permission/
  shebang unit tests (POSIX fixtures); Windows is covered by the unit tests with mocks only.
- 2026-10-07 — `install.sh` installs only for the current user, never with sudo; it writes a
  `~/.local/share/applications/repotray.desktop` menu entry besides the launcher. `uninstall.sh`
  removes manifest-listed paths only when they are under `$HOME`, then removes directories it may
  have created if (and only if) they are empty.
- 2026-10-07 — README screenshots: the panel is rendered offscreen from `--demo` (so no other
  window can leak into it); the tray image is a live `--demo` capture cropped to repotray's icon
  and label.
- 2026-10-07 — The porting guide's example plugin was extracted from docs/porting.md, installed
  into a scratch venv and run (`repotray tray --demo --backend hello`): it works as documented.
- 2026-10-07 — `run_tray` takes the instance lock before writing the default config, so a second
  instance never creates files. (Found in M6: an M3 second-instance check had written the default
  config; it was confirmed identical to the default and then given the maintainer's roots.)
- 2026-10-07 — `test_focus_loss_hides` presents its helper window with the X server timestamp:
  without one, Muffin's focus-stealing prevention occasionally kept focus on the panel (1 flaky
  failure in ~10 runs); the test skips only if the WM still refuses.

## Blocked / unverified
- 2026-10-07 — **Live tray screenshots (M2, M3) while the session is locked.** The maintainer's
  screen locked during the run (cinnamon-screensaver active); root-window captures then show only
  the lock-screen wallpaper. Icons were verified offline with GTK's symbolic loader (contact sheet),
  the panel by rendering it offscreen (`Gtk.OffscreenWindow`). The live checks are repeated whenever
  the session is unlocked during the run; see HANDOFF.md for what remained unverified.
  Update: the session was unlocked again later the same morning; the M2 live icon check and all
  four M3 live checks were then done for real (screenshots in the run's scratchpad, not committed).
- Clicks were simulated over D-Bus (`scripts/dev/click-tray.sh`), never with a real mouse: a real
  click first moves focus to the panel applet, which the 300 ms reopen guard handles (unit-tested,
  not observed live).
- macOS and Windows platforms and the pystray backend there were only unit-tested with mocks.
- `shellcheck` is not installed on the dev machine; the scripts were checked with `bash -n`/`sh -n`
  and an install → reinstall → uninstall round trip into a temporary `HOME`.
- The GitHub workflows have never run (nothing is pushed); YAML was validated locally.
