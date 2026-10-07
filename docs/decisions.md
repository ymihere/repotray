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

## Blocked / unverified
- 2026-10-07 — **Live tray screenshots (M2, M3) while the session is locked.** The maintainer's
  screen locked during the run (cinnamon-screensaver active); root-window captures then show only
  the lock-screen wallpaper. Icons were verified offline with GTK's symbolic loader (contact sheet),
  the panel by rendering it offscreen (`Gtk.OffscreenWindow`). The live checks are repeated whenever
  the session is unlocked during the run; see HANDOFF.md for what remained unverified.
