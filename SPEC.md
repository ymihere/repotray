# repotray — specification (v0.1, starting point)

A system-tray indicator that watches all locally cloned git repositories and shows,
at a glance, how many of them have **local work** (uncommitted changes or unpushed
commits) and how many have **remote work** (commits to pull). Hovering lists which
repos can be pushed or pulled. Clicking opens a panel with the pushable repos on the
left, the pullable ones on the right, and one-click push / pull / sync buttons.
Platform independent; Linux Mint Cinnamon is the first-class target and must look
native there.

Status: spec complete, no code yet (2026-10-05). How it is built — module layout,
interfaces, milestones and acceptance checks — is in `PLAN.md`, which also settles every
question this spec left open.

---

## 1. Definitions

| Term | Meaning |
|---|---|
| Repo | A directory containing `.git` (directory, or file for worktrees). Bare repos are ignored. |
| Dirty | `git status --porcelain=v2` has any entry lines: staged, unstaged, unmerged, or untracked. Ignored files never count. Config can exclude untracked. |
| Ahead | `# branch.ab +A -B` with A > 0 → **pushable**. |
| Behind | `# branch.ab +A -B` with B > 0 → **pullable**. |
| Diverged | Ahead and behind at once. A push would be rejected and a fast-forward pull is impossible → **syncable** (§4.1). |
| No upstream | Current branch has no tracking branch. Listed in its own group, not counted (configurable). |
| Detached | HEAD is detached. Listed, never pushable/pullable. |
| Local work | dirty OR ahead. |
| Remote work | behind. |

The two headline numbers are **counts of repos**, not commits. Commit counts appear in
the per-repo lines (`↑3 ↓1`).

Ahead/behind are computed against the remote-tracking ref, so they are only as fresh
as the last `git fetch`. repotray fetches itself (see §4).

## 2. UX

### 2.1 Icon and label
- Monochrome glyph, transparent background, recolored by the desktop (details §6).
- States:
  - `clean` — the base glyph.
  - `attention` — the base glyph plus up to two **corner dots** in the style of
    Mint's update icon (a filled circle in the bottom-right corner, the glyph cut
    away around it), and/or a **tint** of the whole glyph. The top-right dot, the
    bottom-right dot and the tint each have their own trigger set drawn from `push`
    (≥ 1 repo pushable), `pull` (≥ 1 repo behind) and `dirty` (≥ 1 repo with
    uncommitted changes), and their own theme colour. Default: top-right green dot =
    something to push (up), bottom-right orange dot = something to pull (down, the
    exact spot and colour of "updates available"), both at once when both hold, no
    tint. Any of the three can be switched off; with all off the icon never changes
    and only the label signals work.
  - `error` — the last fetch pass failed for every repo (probably offline) or git is
    missing. The cross is drawn in the theme's error colour, as the mintupdate error
    icon does with its glyph.
  - `paused` — fetching paused by the user (status checks continue).
  Error and paused take precedence over attention.
- Colours are theme **symbolic classes** — `foreground`, `warning`, `error`,
  `success` — so the panel colours them itself and the icon keeps matching its
  neighbours in every theme (§6). A `#rrggbb` value is accepted as an escape hatch,
  at the price of panel recolouring.
- Label next to the icon where the platform supports it (Cinnamon XApp, macOS title),
  composed of the parts listed in `indicator.label`: `↑3` repos pushable, `↓1` repos
  pullable, `✎2` repos dirty. Zero parts are omitted; the label is empty when nothing
  applies and never shown with `label = []`. Where labels are unsupported the counts
  appear in the tooltip and menu only; nothing is drawn into the bitmap (unreadable at
  16 px).

### 2.2 Hover (tooltip)
Grouped list in the panel's order (§2.5: diverged repos first, then by name):

```
Push (2)
  api-gateway        ↑3  ✎
  infra              ↑1
Pull (1)
  website            ↓4
Uncommitted (3)
  api-gateway  notes  scratch
No upstream (1): experiments
Fetched 3 min ago
```

- `✎` marks dirty. A repo may appear in several groups.
- Cap at ~15 repo lines, then `… and N more` (full list in the panel).
- Platform limits: Cinnamon supports multi-line Pango markup (verified in the
  xapp-status applet source: it calls `tooltip.set_markup`). macOS supports multi-line
  plain text. Windows caps tooltips at 127 chars → summary line only. GNOME with
  AppIndicator has no tooltips at all → the panel carries the list.

### 2.3 Click
- **Primary (left) click** → toggles the **panel** (§2.5): a popup anchored to the
  icon with the pushable repos on the left, the pullable ones on the right, and
  one-click push / pull / sync buttons. A second click, Escape, or clicking elsewhere
  closes it.
- **Middle click** → *Fetch all now*.
- **Secondary (right) click** → control menu: *Fetch all now*, *Pause/Resume
  fetching*, *Rescan roots*, *Open config file*, *Autostart* (check item), *About*,
  *Quit*. The panel's gear button holds the same items, so a backend with a single
  click type loses nothing.
- Backends that cannot show a popup window (`caps.panel = false`, e.g. pystray)
  render the panel model as a menu instead: the groups of §2.2 with one *Push* /
  *Pull* / *Sync* item per repo, *Sync all*, then the control items below a
  separator. AppIndicator delivers no click events at all (left click always opens
  its menu), so there the menu starts with *Open panel…* and middle click
  (`secondary-activate`) opens the panel at the pointer; `Gtk.StatusIcon` has
  `activate` and `get_geometry`, so the panel anchors normally.

### 2.4 Notifications
Optional, default **off**: notify when a repo newly becomes *behind* (someone pushed)
and when a fetch starts failing after having worked. Rate limited (one per repo per
hour). Results of user-triggered actions (§4.1) are reported regardless of this
setting: inside the panel while it is open, as a desktop notification otherwise.

### 2.5 Panel
The panel is the primary UI: a small undecorated popup window (not a menu, so it can
hold buttons, live progress and two columns) anchored to the tray icon. Width ≈ 480 px
(scales with the font), height follows the content, the list scrolls beyond ~12 rows.
It is themed by GTK with no hard-coded colours; with `panel_theme = "auto"` it follows
the Cinnamon theme's dark/light choice (PLAN §1), so on Mint-Y-Dark it is a dark box
like Cinnamon's own applet popups even when the GTK theme is light. `( )` below marks a flat icon button, `[ ]` a
labelled button.

```
┌──────────────────────────────────────────────────────────────────────┐
│ 3 repos need attention                       Fetched 3 min ago   (⟳) │
├──────────────────────────────────────────────────────────────────────┤
│ Push (2)                                                    Pull (2) │
│ api-gateway   ↑3 ✎   (↑)        (⇅)           (↓)   ↓4   api-gateway │
│ infra         ↑1     (↑)                                             │
│                                               (↓)   ↓2       website │
├──────────────────────────────────────────────────────────────────────┤
│ ✎ Uncommitted (3)   api-gateway · notes · scratch                    │
│ ⚠ No upstream (1)   experiments                                      │
│ ▸ In sync (8)                                                        │
├──────────────────────────────────────────────────────────────────────┤
│ [ ⇅ Sync all ]                                               [ ⚙ ▾ ] │
└──────────────────────────────────────────────────────────────────────┘
```

**Header.** One summary sentence on the left — `All 12 repos in sync`, `3 repos need
attention`, `Fetching…`, `Offline — fetch failed for every repo, retrying in 8 min`,
`Fetching paused · Resume` — and on the right `Fetched 3 min ago` (relative, refreshed
every minute while open) plus a *Fetch all now* icon button that spins during a fetch
pass. A manual fetch resets the error back-off.

**Columns.** Left `Push (N)`: repos whose branch is ahead of its upstream. Right
`Pull (N)`: repos behind. The columns mirror each other so that the action buttons
meet in the middle gutter: a left row reads `name  ↑3 ✎  (push)`, a right row
`(pull)  ↓4  name`. A *diverged* repo (ahead and behind) occupies one shared row in
both columns with a *Sync* button in the gutter; its push and pull buttons are shown
disabled (tooltip "Diverged — use Sync") because a push would be rejected and a
fast-forward pull is impossible. Shared rows come first, then push-only and pull-only
rows fill their columns independently, sorted by name. Clean repos never appear here.
When nothing is pushable or pullable the columns are replaced by a single centred
`Nothing to push or pull` line.

**Row anatomy.** Name = directory basename, `parent/name` when two repos collide; the
tooltip shows the full path, branch and upstream. Clicking the name opens the repo
context menu: *Open terminal here*, *Open folder*, *Copy path*, *Fetch now*. Markers:
`↑N` / `↓N` commit counts, `✎` uncommitted changes (tooltip reminds that push sends
commits only), `⚠` the last fetch or action failed (tooltip: the error). Buttons are
flat 16 px symbolic theme icons (§6) with tooltips such as "Push 3 commits to
origin/main", "Pull 4 commits (fast-forward)", "Sync: pull --rebase, then push".
Semantics in §4.1.

**Feedback.** While an action runs, its button becomes a spinner and the row's other
buttons are disabled. The status pass that follows the action redraws the row; a row
with nothing left to do disappears and the header shows `Pushed api-gateway ✓` for a
few seconds. On failure the row stays with `⚠`, and the header shows a red banner with
the first line of git's stderr and a *Details…* link to a dialog with the exact
command and full output. Actions keep running if the panel is closed; their results
then arrive as desktop notifications (§2.4).

**Groups below the columns** (each hidden when empty; names are clickable chips with
the same context menu):
- `✎ Uncommitted (N)` — every dirty repo, including those already in the Push column.
- `⚠ No upstream (N)`, `Detached (N)`, `⚠ Fetch failed (N)` (tooltip: the error).
- `▸ In sync (N)` — collapsed expander listing the clean repos, so one can confirm
  that a repo is being watched without the CLI.

**Footer.** *Sync all* on the left: the one labelled, primary button. Disabled with a
tooltip when there is nothing to do; shows `Syncing 2/5…` while running. A gear menu
button on the right holds the control items of the right-click menu: *Fetch all now*,
*Pause fetching* (check), *Rescan roots*, *Open config file* (the v1 "settings"; no
dialog, see §10), *Autostart* (check), *About*, *Quit*.

**Window behaviour.** Toggled by left click; closes on Escape, on focus loss, or on a
second click on the icon. Updates live from every snapshot while open. Keyboard: Tab
between buttons, Enter activates. One instance; opening it never blocks a running
pass. On Cinnamon it is anchored to the icon rectangle and panel side that the XApp
applet reports (§7): centred on the icon, flush with the panel edge, clamped to the
monitor work area. Backends without that information open it at the pointer.

## 3. Discovery (scan)
- Walk each configured root to `max_depth` (default 4).
- Prune directory names in `exclude_dirs` (default: `node_modules`, `.cache`,
  `vendor`, `target`, `build`, `dist`, `venv`, `.venv`, `__pycache__`) and all hidden
  dirs other than `.git`. Pruning applies only *below* a root: a root or `repos`
  entry may itself be hidden (`roots = ["~/.config/nvim"]`) and is always scanned.
  There is no opt-in for discovering hidden directories (decided 2026-10-05).
- Stop descending once a repo is found (`descend_into_repos = false` by default; set
  true to find nested repos / submodules).
- Explicit `repos = [...]` paths are always included, even outside roots.
- `ignore = [...]` globs drop repos from the list.
- Rescan every `rescan_interval` (default 10 min), on demand, and at startup.
  Repos that vanished are dropped silently.

## 4. Status and fetch passes
- **Status pass** every `status_interval` (default 60 s). Per repo:
  `git -C <path> status --porcelain=v2 --branch -z`. Parse only the `# branch.*`
  headers and the first character of each entry (`1`, `2`, `u` → changed; `?` →
  untracked). Local only, cheap. Parallel with `workers` threads (default 4),
  per-call timeout 15 s.
- **Fetch pass** every `fetch_interval` (default 10 min). Per repo:
  `git -C <path> fetch --quiet --no-write-fetch-head --recurse-submodules=no` with an
  environment that can never prompt (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`,
  `GIT_SSH_COMMAND=ssh -oBatchMode=yes`, `GIT_ASKPASS=true`, editors disabled; full
  list in PLAN §4.3). Status calls set `GIT_OPTIONAL_LOCKS=0` so they never write the
  index. Timeout
  default 60 s, concurrency `fetch_workers` (default 4). Never touches the working
  tree or local branches. Per-repo `fetch = false` override for huge repos.
- Fetch failures are recorded per repo and shown as `⚠` in lists. If **all** fetches
  fail, enter `error` state and back off exponentially (×2, up to 60 min) until one
  succeeds.
- A status pass follows every fetch pass.
- All git calls run off the UI thread; UI updates are marshalled to the main thread.
- repotray never modifies a repository except through the explicit actions of §4.1,
  and never asks for credentials.
- Single instance via lock file in the runtime/config dir. CLI subcommands (§8) do
  not take it and may run while the tray runs; two git operations on the same repo
  from both sides are left to git's own locking (worst case an action fails with
  "index.lock exists" and says so).
- Footprint target: ~0 % CPU idle, < 50 MB RSS.
- Filesystem watching (inotify / FSEvents / ReadDirectoryChangesW) is a later
  optimisation; polling is acceptable for v1.

### 4.1 Actions: push, pull, sync
Only ever triggered by the user: a panel button, *Sync all*, or the CLI (§8). They run
on the fetch worker pool, off the UI thread, with the same non-prompting environment
as fetch — so a remote that would need interactive credentials fails fast with a clear
message instead of hanging.

- **Push** = `git -C <path> push` (current branch to its upstream). Never `--force`,
  never `-u`; a repo without upstream has no push button. A dirty working tree does
  not block a push — only commits travel.
- **Pull** = `git -C <path> pull --ff-only`. git itself refuses when the branches
  diverged or when local changes would be overwritten; nothing is modified then.
- **Sync** exists only for diverged repos: `git pull --rebase` (or `--no-rebase` when
  `sync_strategy = "merge"`), then `git push` if the pull succeeded. Refused while the
  repo is dirty (tooltip "Commit or stash first"); auto-stashing around a conflicting
  rebase is exactly the mess this tool should not create. If the rebase/merge stops on
  conflicts, repotray runs `git rebase --abort` / `git merge --abort` and reports the
  failure, so the repo ends up exactly as it was.
- **Sync all** = push every push-only row, pull every pull-only row, sync every
  non-dirty diverged row. Dirty diverged repos are skipped and named in the result.
  Concurrency `fetch_workers`; no cancel in v1.
- A per-repo lock serialises fetch, pull, push and sync on one repo; status reads are
  never locked. A status pass for the repo runs right after each action.
- Timeout `action_timeout` (default 120 s): the process group is killed, then the repo
  is checked for a half-done rebase/merge (`.git/rebase-merge`, `.git/MERGE_HEAD`),
  which is aborted.
- `ActionResult` = repo, action, ok, duration, command, stdout/stderr. Rendered in the
  panel (header banner + row marker) or as a desktop notification when the panel is
  closed; the first stderr line is the message, *Details…* shows everything.

## 5. Configuration
TOML, created with defaults on first run, reloaded automatically when the file changes
(checked at every status pass). Full schema with validation rules: PLAN §4.6.

| Platform | Path |
|---|---|
| Linux | `~/.config/repotray/config.toml` (`$XDG_CONFIG_HOME`) |
| macOS | `~/Library/Application Support/repotray/config.toml` |
| Windows | `%APPDATA%\repotray\config.toml` |

```toml
roots = ["~/code", "~/work"]     # default: ["~"]
repos = []                       # extra repos outside roots
ignore = ["~/work/archive/*"]
max_depth = 4
descend_into_repos = false
exclude_dirs = ["node_modules", "vendor", "target", "build", "dist", "venv", "__pycache__", "snap", "Library", "AppData"]

status_interval = 60             # seconds
fetch_interval = 600
rescan_interval = 600
workers = 4
fetch_workers = 4
fetch_timeout = 60

count_untracked_as_dirty = true
count_no_upstream_as_push = false
notifications = false

sync_strategy = "rebase"         # or "merge": how Sync reconciles a diverged branch
action_timeout = 120             # seconds, for push / pull / sync

# {path} is substituted. Empty = auto-detect per platform (PLAN §4.10).
terminal = ""                      # e.g. "terminator --working-directory={path}"
file_manager = ""                  # Linux xdg-open, macOS open, Windows explorer

backend = "auto"                   # or xapp | appindicator | gtkstatusicon | pystray | a plugin
panel_theme = "auto"               # auto | dark | light | system
log_level = "info"

[indicator]                       # what the tray icon signals; see §2.1 and §6
label = ["push", "pull"]          # parts next to the icon: push ↑N, pull ↓N, dirty ✎N; [] = no label
top_dot = ["push"]                # top-right dot, shown when any of push / pull / dirty applies; [] = never
top_dot_color = "success"         # foreground | warning | error | success | "#rrggbb"
bottom_dot = ["pull"]             # bottom-right dot: the spot Mint's update icon uses
bottom_dot_color = "warning"      # "warning" is the colour of "updates available"
tint = []                         # recolour the whole glyph when any of these apply; [] = never
tint_color = "warning"            # warning | error | success | "#rrggbb"
glyph_color = "#e1e1e1"           # only used when a "#rrggbb" above forces full-colour mode (§6)

[repo."~/work/huge-monorepo"]
fetch = false
name = "monorepo"                  # optional display name
```

Three `[indicator]` examples. *Default:* green dot top-right when you have commits to
push, orange dot bottom-right when someone else pushed, both when both. *Like
mintupdate:* `top_dot = []`, `bottom_dot = ["push", "pull", "dirty"]` → one orange dot
bottom-right whenever anything needs doing, indistinguishable in style from the
update icon next to it. *Quiet:* `label = []`, `top_dot = []`, `bottom_dot = []`,
`tint = ["push", "pull", "dirty"]` → no numbers, no dots, the glyph itself turns
orange when anything needs doing.

## 6. Icons and native look

### Linux Mint / Cinnamon (verified against `/usr/share/cinnamon/applets/xapp-status@cinnamon.org/applet.js`)
- The XApp status applet renders any icon whose **name contains `symbolic`** as
  `St.IconType.SYMBOLIC`, i.e. recolored to the panel foreground. On the current
  Mint-Y-Dark-Aqua panel that is a light gray (~`#e1e1e1`) on transparent — exactly
  the look of the other tray icons. Full-color names or image paths are shown as-is.
- Therefore repotray ships **monochrome SVGs** following the freedesktop symbolic
  convention: 16×16 viewBox, fill `#bebebe`, no strokes, transparent background.
  They are installed to `~/.local/share/icons/hicolor/scalable/status/` (user) or
  `/usr/share/icons/hicolor/scalable/status/` (system) and referenced **by name**.
  Never pre-tint, never pass pixmaps on Linux.
- Installing the files: a `pipx` install cannot write outside its venv, so the tray
  copies missing or outdated icons from package data into
  `~/.local/share/icons/hicolor/scalable/status/` at startup; a distro package puts
  them under `/usr/share/icons/…` instead and the copy step finds nothing to do.
- Colour inside a symbolic icon comes from the GTK symbolic **classes**: elements
  with `class="warning"`, `"error"` or `"success"` are filled by the panel with the
  theme's `warning-color` / `error-color` / `success-color`, everything else with the
  foreground colour. libst exposes exactly those CSS properties (verified in the
  binary); Mint-Y-Dark-Aqua sets `warning-color: #F27835` for some icons and libst's
  built-in orange / red / green defaults cover the rest — confirm the rendered values
  on the panel in M2. This is how the dots and the tint of §2.1 get their colour while
  the icon stays symbolic and theme-matched.
- **Reference: Mint's own update icon** (`/usr/share/icons/hicolor/scalable/status/
  mintupdate-updates-available-symbolic.svg`, read on the dev machine): the glyph is
  filled `#bebebe`; the dot is `<path class="warning" style="fill:#f57900" …>`, a
  circle of radius 3 centred at (13, 13) in the 16×16 box, i.e. touching the
  bottom-right corner; the glyph path is cut away in a radius-4 circle around the
  dot, leaving a 1 px transparent ring that keeps the dot legible on any background.
  `mintupdate-error-symbolic.svg` gives its glyph `class="error"` (`#e01b24`).
  repotray copies this geometry exactly: **bottom-right dot** centred (13, 13),
  **top-right dot** centred (13, 3), both radius 3 with a radius-4 knockout; the
  fallback fills are `#f57900` warning, `#e01b24` error, `#2ec27e` success,
  `#bebebe` foreground (only renderers without class support ever see them).
- The knockout is baked into the glyph path by the build script (boolean
  difference), never done with an SVG mask or clip: GTK's symbolic loader rewrites
  the fills of every element, which would recolour a mask too. One template holds
  the glyph, the two dot circles and the cross/bars; the script emits every
  combination `repotray[-tint-<c>][-top-<c>][-bottom-<c>]-symbolic.svg` with tint ∈
  {warning, error, success} and each dot ∈ {foreground, warning, error, success}
  (4 × 5 × 5 = 100 small files, ≈ 1 KB each, incl. the plain `repotray-symbolic.svg`),
  plus `repotray-error-symbolic.svg` and `repotray-paused-symbolic.svg`. Static files
  rather than runtime generation, so system-wide installs and icon-theme caches need
  no special handling. The backend composes the name from the `IconSpec` (§7).
- A `#rrggbb` colour in `[indicator]` forces **full-colour mode**: repotray renders the
  SVG with literal fills to `$XDG_CACHE_HOME/repotray/icon-<hash>.svg` and passes the
  **path**. The applet loads any name containing `/` but not `symbolic` as an image
  file shown as-is (verified in `setIconName`), so the panel no longer recolours it:
  untinted parts use `glyph_color` (default `#e1e1e1`, the Mint-Y dark panel
  foreground; set it for a light panel). The filename must never contain "symbolic".
- The applet also shows the `label` property on horizontal panels, and tooltips accept
  Pango markup — both used as described in §2.
- Other Linux desktops: KDE/XFCE via StatusNotifierItem or AppIndicator (icon by
  theme name, so the same symbolic SVGs work; KDE recolors symbolic icons too).
  GNOME needs the AppIndicator extension; no tooltip there, the label and the panel carry the counts.

### macOS
Template images (black glyph + alpha, `isTemplate = true`) so the menu bar tints them
for light/dark mode. Counts shown as the status item's title. A tint switches the
image to non-template in that colour (theme class names map to fixed orange / red /
green); the dots are drawn into the image.

### Windows
Light-gray glyph on transparent for the default dark taskbar; read
`HKCU\...\Personalize\SystemUsesLightTheme` and switch to a dark glyph on light
taskbars. Dots and tint are drawn into the image; counts live in the tooltip.

### Panel and menu icons
Buttons use theme icons by name, so they follow the GTK theme like the rest of the
panel: `go-up-symbolic` (push), `go-down-symbolic` (pull),
`emblem-synchronizing-symbolic` (sync, Sync all), `view-refresh-symbolic` (fetch now),
`emblem-system-symbolic` (gear), `dialog-warning-symbolic` (⚠),
`document-edit-symbolic` (✎), `object-select-symbolic` (✓). All present in Adwaita,
which Mint-Y inherits. Only the tray icon itself is
shipped by repotray.

### Glyph
**The Octicon `repo`** (primer/octicons, MIT): the small book GitHub shows next to
every repository name, so it is immediately associated with GitHub without being one
of its trademarks, and it matches the name repotray. It is a native 16 px icon
(outline from x = 2 to 14, bookmark ribbon at x = 5–9 along the bottom). The two
corner knockouts only notch its top-right and bottom-right corners — exactly how
mintupdate's shield is notched — so it stays recognisable with either or both dots
shown; the ribbon just clears the bottom-right ring. Verified in the live Cinnamon tray
on 2026-10-05 at scale 1.0 with green and orange dots. The icon can be swapped later:
only the template changes. Fallbacks, in order, if it does not read well on the
panel at 16 px and 22 px: the Octicon `git-branch` (its node at (11.75, 3.25) sits
inside the top-right knockout, so it would need scaling to ≈ 12 px and a shift
left), then the Git logo by Jason Long (CC BY 3.0, attribution in *About*).
Not the GitHub logo: GitHub's brand guidelines (brand.github.com/foundations/logo,
read 2026-10-05) say "Do not use any GitHub logo as the icon or logo for your …
project" and forbid modified versions, which rules out the Invertocat and equally
the cat silhouette taken out of its circle — the silhouette is the mark, the circle
only its frame. The Octicons MIT notice ships in the package and appears in *About*.
`error` adds a small cross; `paused` two bars.

## 7. Architecture

The authoritative module layout, data types and interfaces are in PLAN §3–§4. In short:

- **core** (stdlib only): scanner, git runner, porcelain parser, actions, scheduler, and
  pure functions that turn a `Snapshot` into an `IconSpec`, label, tooltip and
  `PanelModel`. No GUI imports, so the CLI runs headless.
- **platform**: one `Platform` protocol for OS services (paths, terminal, folder,
  autostart, notifications fallback, process groups, instance lock, icon install), with
  Linux, macOS and Windows implementations.
- **backends**: one `TrayBackend` protocol with declared `Capabilities`, a registry that
  probes and scores the available backends, and the built-ins `xapp`, `appindicator`,
  `gtkstatusicon`, `pystray` and `fake`. Third parties add backends as separate packages
  through the `repotray.backends` entry point, without touching the core.
- **ui/gtk3**: the panel, shared by the Linux backends. A backend without a panel gets
  the same content as a menu.
- **app**: the `Controller`, the only API a UI calls (fetch, push, pull, sync, sync all,
  pause, open terminal, …).

Porting to an untested desktop or OS means implementing a backend and/or a platform,
running the conformance suite and filing a platform report (docs/porting.md).

**Cinnamon specifics (verified on the dev machine).** `XApp.StatusIcon` emits
`button-press-event` and `button-release-event(x, y, button, time, panel_position)`;
the xapp-status applet fills `x, y` with the icon's screen edge adjacent to the panel
(from the actor allocation, divided by `ui_scale`) and `panel_position` with a
`Gtk.PositionType`. `activate(button, time)` carries no position. So: leave the
primary menu unset, open the panel from the release event for button 1, keep
`set_secondary_menu` for button 3. (M2 confirms that the release signal fires for
button 1 with no primary menu bound; the applet forwards every click.) The panel is a
`Gtk.Window`: undecorated, skip-taskbar, keep-above, not override-redirect so it can
take keyboard focus; exact type hint settled in M2.

**Recommended stack: Python ≥ 3.11** (stdlib `tomllib`, `subprocess`,
`concurrent.futures`). Rationale: PyGObject with XApp and AppIndicator typelibs is
already present on the Mint dev machine (verified), it is the fastest path to a
native Cinnamon result, and the core is trivially portable. XApp-1.0 binds to Gtk 3,
so the panel is Gtk 3 everywhere on Linux. macOS/Windows: `pystray` + `Pillow` give
the icon and the menu fallback only, since pystray cannot host a panel; v1 ships that
(§11), and native panels (PyObjC `NSPopover`, a frameless Tk or Qt window) are left to
contributors. Distribution: `scripts/install.sh` on Linux (needs no pip), `pipx install
--system-site-packages repotray` once on PyPI, PyInstaller bundles for macOS/Windows
later.

*Alternative considered:* Go (`fyne.io/systray`) or Rust (`tray-icon`, `ksni`) for a
single static binary. Rejected for v1 because those libraries pass pixmap icons on
Linux, which Cinnamon will not recolor, tooltip support is inconsistent, and the panel
would need a GUI toolkit on top anyway. Revisit if distribution outweighs Cinnamon
fidelity.

## 8. CLI
```
repotray [tray] [--demo]         start the tray (default); --demo shows fabricated repos
repotray status [--json] [--demo]  one status pass, print table or JSON, exit
repotray scan [--absolute]       list discovered repos and exit
repotray fetch [REPO...]         fetch pass + status, exit
repotray push REPO...            git push (§4.1); REPO = name, basename or path
repotray pull REPO...            git pull --ff-only
repotray sync [--all | REPO...]  per repo: push if ahead, pull --ff-only if behind,
                                 pull --rebase + push if diverged; --all = Sync all
repotray doctor                  environment, config, backends and icons report
repotray config path|default     config file location / default config
repotray autostart enable|disable|status
                                 Linux: ~/.config/autostart/repotray.desktop
                                 macOS: ~/Library/LaunchAgents/io.github.repotray.plist
                                 Windows: HKCU\…\Run registry value
repotray icons install|uninstall user icon theme files (Linux)
repotray quit                    stop the running tray
repotray --config PATH  --backend NAME  --verbose  --version
```
`status`, `scan`, `doctor` and the action commands make the core testable and useful
without any GUI. Exit codes and the JSON schema: PLAN §4.14.

## 9. Testing
- Unit tests for the porcelain-v2 parser with fixtures: clean, staged, unstaged,
  untracked-only, unmerged, ahead, behind, ahead+behind, no upstream, detached,
  initial commit (`branch.oid (initial)`).
- Integration test: build a bare "remote" and two clones in a temp dir with real git,
  create ahead/behind/dirty situations, assert `repotray status --json`.
- Action tests on the same fixture: push clears ahead; `pull --ff-only` clears behind;
  diverged → sync rebases and pushes; diverged with a conflicting edit → sync aborts
  and HEAD, index and working tree are identical to before; dirty diverged → sync
  refused without running git; a remote needing credentials fails fast, no hang.
- Model tests: `PanelModel` row allocation (shared rows first, then by name), button
  enablement rules, basename collisions, empty state, menu fallback rendering.
- Indicator tests: label parts and omission of zeros, top-dot / bottom-dot / tint
  trigger sets (incl. `count_no_upstream_as_push`), error/paused precedence, icon name
  composition, hex colour → path mode with a filename free of "symbolic". Build-script
  test: every emitted SVG parses, has the dot circles only where named, and the glyph
  path has no pixels inside a shown dot's radius-4 ring.
- Scanner tests: depth, exclusions, nested repos, symlink loops.
- Manual checklist on Cinnamon: icon recolored like neighbours, bottom-right dot looks
  identical in size, place and colour to mintupdate's, top-right dot clearly separate,
  tint shows the theme colour, hex mode shows as-is, label parts and `label = []`;
  tooltip multi-line with markup; panel opens anchored to the icon on a top and a
  bottom panel, closes on Escape / focus loss / second click, buttons spin and report
  results, Sync all progress, gear menu; right-click menu; actions open
  terminator/Nemo; autostart entry; survives suspend/resume and network loss (error
  state, backoff, recovery).

## 10. Non-goals for v1
GUI settings dialog; GitHub/GitLab API data (PRs, CI, issues); auto-commit or
auto-pull; stash tracking; multiple remotes beyond the upstream; submodule recursion
by default; filesystem event watching; packaging for distros.

## 11. Decisions on former open questions
All settled on 2026-10-05; details in PLAN §1.
- Label counts **repos**, never commits.
- Sync = `git pull --rebase` then `git push`; `merge` is the only alternative.
- Hidden directories are never discovered; a hidden directory can be a root or a
  `repos` entry.
- Icon: Octicon `repo`, verified in the tray. Not the GitHub mark, not the Octocat
  silhouette without its circle.
- Defaults `fetch_interval = 600` and `notifications = false` stay.
- macOS/Windows ship with the pystray menu fallback in v1, marked experimental; native
  panels there are the top porting opportunity.
- Licence MIT.

## 12. Milestones
M0 skeleton · M1 headless core + CLI · M2 icons · M3 Cinnamon backend + panel ·
M4 other backends and platforms · M5 docs, scripts, CI, packaging · M6 final acceptance
and hand-off. Deliverables and acceptance checks: PLAN §5.
