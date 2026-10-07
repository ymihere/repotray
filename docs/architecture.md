# Architecture

The authoritative design is in [PLAN.md](../PLAN.md) §3–§4; this page is the overview.

## Layers

```
core  ←  platform  ←  app  ←  backends / ui
```

An arrow means "may import". Enforced by `tests/unit/test_layering.py`, which blocks `gi`,
`pystray`, `PIL` and `PySide6` and imports every headless module.

| Package | Contents | Imports |
|---|---|---|
| `repotray.core` | types, git runner, porcelain parser, scanner, config, actions, scheduler, presentation models (indicator, tooltip, panel model, menus), demo data | stdlib only |
| `repotray.platform` | the `Platform` protocol: directories, terminal/folder/file opening, notifications fallback, autostart, instance lock, process groups, icon installation; Linux, macOS, Windows | stdlib (+ `fcntl`, `msvcrt`, `winreg` lazily) |
| `repotray.icons` | icon names, full-colour SVG (hex mode), Pillow rasters — all from the committed `data/` | stdlib (Pillow lazily in `raster`) |
| `repotray.app` | `Controller` (the only API a UI calls), tray startup | core, platform |
| `repotray.backends` | `TrayBackend` protocol, registry, built-in backends | gi / PySide6 / pystray inside each backend module |
| `repotray.ui` | `placement` (pure geometry), `text` (dialog texts); `gtk3` (panel, menus, details, theme); `qt` (the same panel, menus and dialogs in Qt 6, icons, Win32 helpers) | gi in `gtk3`, PySide6 in `qt` only |
| `repotray.cli` | argparse front end; headless except `tray` | core, platform |

## Threads and data flow

```
                 ┌─────────────────────── scheduler thread ───────────────────────┐
  timers ──────▶ │ rescan → status pass → snapshot                                │
  commands ────▶ │ fetch pass ──▶ fetch pool ──┐                                  │
 (fetch_now,     │ actions    ──▶ fetch pool ──┤ completions posted back as        │
  run_action,    │ status     ──▶ status pool ─┘ commands; state written only here │
  sync_all, …)   └─────────────────────────────┬──────────────────────────────────┘
                                               │ Snapshot (immutable)
                                               ▼
                         Controller._on_snapshot  ──backend.call_soon──▶  UI thread
                                                                            │
           icon_spec / label_text / tooltip_text / panel_model / menus  ◀───┘
                                               │
                                               ▼
                    backend.set_icon / set_label / set_tooltip / set_menus / show_panel_model
                                               │
                     clicks ──▶ Controller.dispatch(action, path) ──▶ scheduler commands
```

- **One writer.** All mutable scheduler state is written on the scheduler thread. Pools only run
  git; their results come back as queued commands.
- **Snapshots are immutable** frozen dataclasses; the presentation models are pure functions of
  `(snapshot, config, now)` and are unit-tested without any GUI.
- **git** is only ever spawned by `core/gitrun.py`: own process group, non-interactive environment,
  timeouts that kill the whole group.
- **Locks.** One lock per repository serialises fetch, push, pull and sync; status reads are never
  locked. A fetch pass skips a locked repository instead of waiting.
- **Backoff.** When every fetch in a pass fails, the next pass waits twice as long (up to an hour)
  and the icon shows the error state; any success or a manual *Fetch all now* resets it.
- **Resume.** Each loop compares wall-clock and monotonic deltas; a gap over 60 s means the machine
  slept, and a fetch pass follows 10 s later.

## Actions

`core/actions.py` re-reads the repository's status under its lock, re-checks the button's
preconditions and only then runs git:

- push: `git push --porcelain <remote> refs/heads/<branch>:<merge>`
- pull: `git pull --ff-only --no-rebase --quiet`
- sync: `git pull --rebase --no-autostash` (or `--no-rebase --no-edit`), then push; on failure or
  timeout, `rebase --abort` / `merge --abort`, then verify HEAD and the absence of an operation in
  progress → `ActionResult.restored`.

## Panel

`ui/gtk3/panel.py` (Linux): `PanelView` lays out a `PanelModel` and rebuilds only the sections whose
model changed; `Panel` is the undecorated window: placement from `ui/placement.py`, hide on Escape,
focus loss or a second click, and a 300 ms guard against the click that caused the focus loss
reopening it. `scripts/dev/render-panel.py` renders the view offscreen.

`ui/qt/panel.py` (Windows, `qt` backend) is the same design in Qt 6, widget for widget, with the
same behaviour. Qt-specific: `Panel.fit()` delivers pending layout requests before resizing (Qt
computes nested layouts lazily), the window is re-placed whenever its size changes so it stays flush
with the taskbar, and if Windows refuses to give the new panel focus it asks once through
`ui/qt/winapi.py` — without focus it could not notice a click elsewhere.
`scripts/dev/render-panel-qt.py` renders it to PNGs.

## Icons

`tools/build_icons.py` (dev-only; shapely, svgpathtools) turns the Octicon `repo` glyph into 102
symbolic SVGs with the dot knockouts baked into the path, plus `geometry.json`, which
`icons/svg.py` (full-colour mode) and `icons/raster.py` (pystray, Qt) draw from. The output is committed;
a test regenerates it and compares.
