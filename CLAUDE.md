# repotray

Tray indicator that watches all local git clones and shows how many have local work
(uncommitted/unpushed) and remote work (to pull); hover lists which repos to push/pull,
click opens a panel with push / pull / sync buttons.

- **`SPEC.md`** — what repotray does (behaviour, UX). Change it when a decision changes.
- **`PLAN.md`** — how to build it: layout, interfaces, milestones, acceptance checks. An agent
  implementing repotray follows PLAN.md milestone by milestone without needing to ask.
- **`CLAUDE.local.md`** (gitignored, may be absent) — facts about the maintainer's dev machine.

## Status (2026-10-07)
M0–M2 done (skeleton; headless core, platform layer, CLI; icons). Next: PLAN.md milestone M3. Implementation choices are
logged in `docs/decisions.md`.

## Decisions already made
- Name: repotray. Licence: MIT. Python ≥ 3.11, zero PyPI runtime dependencies on Linux.
- Platform independent core; Linux Mint Cinnamon is the first-class target. Other desktops/OSes plug in
  through the backend and platform registries (PLAN §4); contributors port without touching the core.
- On Cinnamon the icon must match the other tray icons: monochrome **symbolic** SVG recoloured by the
  panel. Reference icons by theme name, never pixmaps.
- Left click opens a **panel** (Gtk 3 window, not a menu): pushable repos left, pullable right, buttons
  meeting in a middle gutter; diverged repos get a shared row with a *Sync* button; *Sync all* and a gear
  menu in the footer. Right click = control menu, middle click = fetch all. SPEC §2.5, §4.1.
- Sync = `git pull --rebase` then `git push`; `merge` is the only alternative. Never auto-stash, abort on
  conflicts, so a failed action leaves the repo as it was.
- Icon signalling is configurable (`[indicator]`): label parts, a top-right dot, a bottom-right dot and a
  tint, each with its own trigger set and theme colour. Defaults: green top-right = push, orange
  bottom-right = pull (Mint's "updates available" spot and colour). Dot geometry copies
  mintupdate-updates-available-symbolic.svg: r=3 at (13,13)/(13,3), glyph knocked out r=4 (baked into the
  path, no masks).
- Glyph: Octicon `repo` (MIT), GitHub-associated without being a trademark. **Not the GitHub logo**, not
  the Octocat silhouette without its circle either (brand.github.com forbids both, checked 2026-10-05).
- Label counts repos only. Hidden directories are never discovered; a hidden dir can be a root.

## Conventions
- Never let repotray modify a repo except via the explicit Push/Pull/Sync actions (panel buttons,
  Sync all, CLI); never prompt for credentials; never `--force`.
- All git calls off the UI thread.
- Nothing under `repotray/core/` or `repotray/platform/` imports gi or any GUI toolkit, so the CLI runs headless.
