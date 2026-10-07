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
  *Superseded the same day:* the integration tests run on Windows too (see "Windows: Qt backend").
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

### After 0.1.0 (maintainer feedback, 2026-10-07)

- Corner markers are ▲ (push, top-right) / ▼ (pull, bottom-right) by default; `[indicator] marker =
  "dot"` keeps the Mint-style dots. The trigger keys stay `top_dot` / `bottom_dot` (renaming them
  would break existing configs; their meaning is "top-right / bottom-right marker"). Triangle size:
  7 wide × 6 high in the corner box, knocked out with a 1 px margin — a 6-wide candidate was compared
  side by side at 16/24/32 px and read worse at 16 px. Arrow files are named `-up-` / `-down-` so the
  dot names stay valid. The glyph knockout for error/paused remains the dot shape.
- Panel: one row per repo (push cell left, pull cell right, sync for diverged), sorted by name;
  `panel_sort = "state"` sorts syncable → pushable → pullable. Push-only and pull-only repos never
  share a row any more.
- Bulk buttons at the top: *Push all* (left, above the push column), *Sync all* (centre, primary),
  *Pull all* (right). Push all / Pull all skip diverged repos and say so in the tooltip and result.
  The gear moved to the header; the footer is gone. One bulk action runs at a time; the others are
  disabled meanwhile. `Snapshot.sync_all` became `Snapshot.bulk = (kind, done, total)`.
- CLI: `repotray push --all` / `pull --all`; `sync --all` uses the same plan as the panel and prints
  skipped repos instead of failing on them.
- After installing new icon files the tray sets its icon again 6 s later: the applet can look up a
  just-installed name before GTK's icon theme rescans and show a blank icon (seen once live).
- The maintainer confirmed real mouse clicks work (2026-10-07), and sees the counts next to the
  icon with the default XApp backend. Only the AppIndicator route on Cinnamon (via
  `xapp-sn-watcher`) drops the label — re-checked the same day.
- Both markers default to `warning` (orange): the maintainer found the green ▲ hard to see.
  `top_dot_color = "success"` brings the green back.
- *Open terminal here* asks the desktop first: on Mint the Debian `x-terminal-emulator`
  alternative pointed to terminator while Cinnamon's Preferred Applications (and
  `xdg-terminals.list`) said gnome-terminal, and repotray had picked terminator. Order now: config
  `terminal` > desktop setting by `XDG_CURRENT_DESKTOP` (Cinnamon, MATE, GNOME-family gsettings) >
  XDG `xdg-terminals.list` > `x-terminal-emulator` > known terminals. A preferred terminal repotray
  does not know is started with the repository as its working directory.
- *Show incoming commits (N)…* is the first repo-menu item when the repo is behind (cells and
  chips now carry their own menu). It runs `git log HEAD..@{upstream}` off the UI thread (read
  only; as of the last fetch, no fetch first) and shows up to 200 commits in a dialog that keeps
  the panel open. *Open in editor* writes the whole log (up to 5000 commits, `git log` medium
  format) to `~/.cache/repotray/incoming-<name>.txt` and opens it with `editor`, else `xdg-open`
  (xed on Mint). Backends without dialogs open the editor directly. Only incoming commits were
  asked for; outgoing ones are not listed.
- The incoming-commits dialog has a primary button that brings the commits in: *Pull* when the
  repo is only behind, *Sync* when it diverged (a fast-forward pull cannot work there), with the
  panel row's rules and tooltips. Clicking it starts the action and closes the dialog; progress and
  the result appear in the panel (or as a notification when it is closed). When blocked
  (uncommitted changes on a diverged branch, operation in progress, busy) it is disabled and the
  reason is printed under the dialog's heading, because insensitive buttons may hide tooltips.

### Windows: Qt backend (2026-10-07)

The maintainer asked for the panel on Windows ("apps like Keybase and Dropbox show rich UI on left
click"). Done on a Windows 11 machine (Python 3.13, Git 2.45, PySide6 6.11).

- Toolkit: **Qt 6 via PySide6** (`backends/qt.py`, `ui/qt/`), not Tk. `QSystemTrayIcon` reports
  left/middle/right clicks and the icon rectangle, so one toolkit covers icon, panel, menus,
  dialogs and notifications. Tk would have needed pystray for the icon (no left click, no icon
  position) plus Win32 calls, and two event loops. Cost: `PySide6-Essentials` (73 MB wheel on
  Windows, checked on PyPI) replaces pystray as the Windows dependency; pystray stays for macOS and
  as the `pystray` extra. Minimum PySide6 6.8 (`QStyleHints.setColorScheme`).
- Probe scores: `qt` 70 on Windows (beats pystray's 50), 40 on macOS (untested there, below
  pystray), 5 on Linux (the GTK backends match Cinnamon; Qt would show pixmaps).
- The Qt panel copies the GTK panel widget for widget (same grid columns, sections, rebuild rules,
  300 ms reopen guard, 2 s refresh tick, dialogs that keep the panel open). Toolkit-free texts moved
  to `ui/text.py` (details text, commit date parsing, dialog strings) and the icon-side inference of
  `gtkstatusicon` to `ui/placement.anchor_from_icon`, so neither is duplicated.
- Window: frameless `Qt.Tool` + stay-on-top; Windows 11 rounds its corners and adds the flyout
  shadow through `DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)`. Windows 10
  ignores the call (square corners).
- Theme: `panel_theme = "auto"` follows `SystemUsesLightTheme` (the taskbar), like Windows' own tray
  flyouts, via `QStyleHints.setColorScheme`; Qt's `windows11` style draws both schemes.
- Icons: the model's GTK icon names map to Segoe Fluent Icons / Segoe MDL2 Assets glyphs, painted
  in the palette's text colour by a small `QIconEngine` (Qt's own theme icons have no gear);
  freedesktop theme names elsewhere, a text arrow as last resort (Qt's offscreen platform has no
  icon font, so the tests see the text). Banner colours are WinUI's InfoBar critical/success
  colours, light and dark — Windows has no theme colour for errors.
- Tray icon: one pixmap per size 16, 20, 24, 32, 40, 48, 64 px from `icons/raster.py`, so Windows
  never shrinks a 64 px bitmap to 16 px (checked on a contact sheet on light and dark taskbars).
- Sizing: Qt computes nested layouts lazily, so `adjustSize()` right after a model change used
  stale sizes and squeezed rows over the groups (seen in the first render). `Panel.fit()` delivers
  pending `LayoutRequest`s first; the window is re-placed on every resize so it stays flush with the
  taskbar when rows come and go.
- Focus: the panel closes when it loses activation (60 ms re-check, unless a menu or one of its
  dialogs is open). If Windows' foreground lock refuses to activate it, it asks once with
  `AttachThreadInput` + `SetForegroundWindow` — only if it never had focus since being shown (a
  first version also did it after the user had clicked elsewhere and stole focus back; a test
  caught it).
- Clicks: `Trigger` toggles the panel, `MiddleClick` fetches, `Context` shows the control menu.
  With the icon in the hidden-icons overflow, `QSystemTrayIcon.geometry()` reports the `^` button
  (measured: `QRect(1626, 1152, 32, 48)` on a 1920×1200 screen), so the panel opens above it.
- `call_soon` emits a signal with an explicit queued connection, so even a call from the Qt thread
  runs later, never re-entrantly (GLib's `idle_add` behaves the same).
- Windows fixes found on the way: (1) `GIT_SSH_COMMAND="ssh -oBatchMode=yes"` overrode
  `core.sshCommand` (the maintainer's is `C:/Windows/System32/OpenSSH/ssh.exe`) and `GIT_SSH`; now
  the repo's `core.sshCommand` is read before each fetch/action (≈ 50 ms measured on Windows) and
  batch mode appended (`-batch` for plink). (2) CLI output to a pipe crashed on `↑` (cp1252); the
  CLI writes UTF-8 on Windows. (3) `cmd /K` was started with git's `CREATE_NO_WINDOW` — invisible;
  helpers now get `CREATE_NEW_CONSOLE` (`wt.exe` is a GUI program, checked, so it is unaffected).
  (4) Windows templates were split on spaces, breaking quoted program paths. (5) Autostart ran
  `repotray.exe` (a console window at login); it now uses the new `repotrayw` gui-script.
  (6) Paths showed as `~/code\x`: the `~` helper existed four times (cli, scanner, model, and an
  unused one in tooltip); now one `core.config.abbreviate` with the OS separator.
- The real-git integration tests run on Windows (all 28 pass, including the pre-receive hook
  test: Git for Windows runs `#!/bin/sh` hooks without chmod).
- Verified on Windows 11: unit + integration tests; the Qt panel tests and the conformance suite
  both offscreen and on the real desktop (`REPOTRAY_GUI_TESTS=1`); a live `--demo` run that opened
  the panel above the tray (screenshot: flush with the taskbar, rounded corners, light theme).
  Not verified by a person yet: a real mouse click on the tray icon.

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
  (Windows: tested on a real machine since 2026-10-07, see above; macOS still mocks only.)
- `shellcheck` is not installed on the dev machine; the scripts were checked with `bash -n`/`sh -n`
  and an install → reinstall → uninstall round trip into a temporary `HOME`.
- The GitHub workflows have never run (nothing is pushed); YAML was validated locally.
- 2026-10-07 — `docs/images/tray.png` re-captured live from `--demo` with both markers orange
  (the session had been locked when the orange default landed). The maintainer confirmed that
  gnome-terminal and xed now open as expected.
