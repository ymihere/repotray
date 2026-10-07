# Configuration

repotray reads one TOML file:

| Platform | Path |
|---|---|
| Linux | `~/.config/repotray/config.toml` (honours `$XDG_CONFIG_HOME`) |
| macOS | `~/Library/Application Support/repotray/config.toml` |
| Windows | `%APPDATA%\repotray\config.toml` |

`repotray config path` prints it, `repotray config default` prints the fully commented default.
The tray writes the default on first start and **reloads the file automatically** when it
changes (checked at every status pass). Every key is optional.

Invalid values never stop the tray: a key with a wrong type or out-of-range value falls back to its
default and a warning appears in the panel header and in `repotray doctor`; unknown keys are
reported the same way. If the file is not valid TOML, the previous settings stay in force and the
panel shows the parse error.

## Discovery

| Key | Type | Default | Notes |
|---|---|---|---|
| `roots` | list of paths | `["~"]` | Directories searched for clones. `~` and `$VARS` are expanded. A root may itself be hidden (`~/.config/nvim`). |
| `repos` | list of paths | `[]` | Extra repositories, always included, even outside the roots or hidden. |
| `ignore` | list of globs | `[]` | Repositories whose absolute path matches are dropped (`"~/work/archive/*"`). |
| `max_depth` | int 0–12 | `4` | How deep below each root to look; the root is depth 0. |
| `descend_into_repos` | bool | `false` | Look inside repositories for nested ones (vendored libraries, submodules). |
| `exclude_dirs` | list of names | `["node_modules", "vendor", "target", "build", "dist", "venv", "__pycache__", "snap", "Library", "AppData"]` | Directory names never descended into. Hidden directories (leading `.`) are always skipped below a root. |

Directory symlinks below a root are never followed (roots themselves may be symlinks). Repositories
that disappear are dropped silently at the next rescan.

## Timing and concurrency

| Key | Type | Default | Notes |
|---|---|---|---|
| `status_interval` | seconds ≥ 10 | `60` | Local `git status` of every repository. Cheap, never touches the network. |
| `fetch_interval` | seconds ≥ 60 | `600` | `git fetch` of every repository. Doubles (up to 1 h) while every fetch fails. |
| `rescan_interval` | seconds ≥ 60 | `600` | Re-walk the roots for new or removed clones. |
| `workers` | 1–32 | `4` | Parallel status checks. |
| `fetch_workers` | 1–32 | `4` | Parallel fetches and actions. |
| `fetch_timeout` | seconds 5–600 | `60` | Per-repository fetch timeout; the git process group is killed. |
| `action_timeout` | seconds 10–1800 | `120` | Timeout for push, pull and sync. A timed-out sync aborts its rebase/merge. |

## Counting

| Key | Type | Default | Notes |
|---|---|---|---|
| `count_untracked_as_dirty` | bool | `true` | Untracked files make a repository "dirty" (✎). |
| `count_no_upstream_as_push` | bool | `false` | Count branches without an upstream as "to push" (they still get no Push button). |
| `notifications` | bool | `false` | Desktop notification when a repo falls behind (someone pushed) or fetching starts failing; at most one per repo and kind per hour. Results of your own actions are always reported. |

## Actions

| Key | Type | Default | Notes |
|---|---|---|---|
| `sync_strategy` | `"rebase"` \| `"merge"` | `"rebase"` | How Sync reconciles a diverged branch: `git pull --rebase` or `git pull --no-rebase`, then `git push`. |
| `terminal` | command template | `""` | *Open terminal here*. `{path}` is substituted into each argument after splitting; no shell is involved. Empty = auto-detect (`x-terminal-emulator` target, gnome-terminal, terminator, xfce4-terminal, mate-terminal, konsole, tilix, kitty, alacritty, wezterm, foot, xterm; macOS Terminal; Windows Terminal or cmd). Example: `"kitty --directory {path}"`. |
| `file_manager` | command template | `""` | *Open folder*. Empty = `xdg-open` / `open` / `explorer`. Example: `"nemo {path}"`. |

## Appearance and backend

| Key | Type | Default | Notes |
|---|---|---|---|
| `backend` | string | `"auto"` | `auto`, `xapp`, `appindicator`, `gtkstatusicon`, `pystray`, `fake` or a plugin's name. `--backend` and `$REPOTRAY_BACKEND` override it. |
| `panel_sort` | `name` \| `state` | `"name"` | Order of the panel's rows: alphabetical, or syncable (diverged) first, then pushable, then pullable — each group alphabetical. |
| `panel_theme` | `auto` \| `dark` \| `light` \| `system` | `"auto"` | `auto` follows the Cinnamon panel theme (dark if its name contains "dark"), so the panel matches Cinnamon's own popups even when the GTK theme is light. `system` leaves GTK alone. |
| `log_level` | `debug` \| `info` \| `warning` | `"info"` | Log file: `~/.local/state/repotray/repotray.log`. |

## `[indicator]` — what the tray icon signals

Three signals — a marker in the top-right corner, one in the bottom-right corner, and a tint of
the whole glyph — each with its own trigger set drawn from `push` (≥ 1 repo to push), `pull`
(≥ 1 repo behind) and `dirty` (≥ 1 repo with uncommitted changes). By default the markers are
arrows: a ▲ top-right for something to push, a ▼ bottom-right for something to pull.

| Key | Type | Default | Notes |
|---|---|---|---|
| `label` | list ⊆ {push, pull, dirty} | `["push", "pull"]` | Text next to the icon: `↑N` repos to push, `↓N` to pull, `✎N` dirty; in this order; zero parts omitted; `[]` = no label. |
| `marker` | `arrow` \| `dot` | `"arrow"` | Shape of the corner markers: ▲ top-right / ▼ bottom-right, or round dots exactly like Mint's update icon. |
| `top_dot` | list ⊆ {push, pull, dirty} | `["push"]` | The top-right marker (▲ or dot). `[]` = never. (The key keeps its name for both shapes.) |
| `top_dot_color` | colour | `"success"` | `foreground`, `warning`, `error`, `success` or `"#rrggbb"`. |
| `bottom_dot` | list ⊆ {push, pull, dirty} | `["pull"]` | The bottom-right marker (▼ or dot) — where Mint's update icon puts its dot. |
| `bottom_dot_color` | colour | `"warning"` | `warning` is the colour of "updates available". |
| `tint` | list ⊆ {push, pull, dirty} | `[]` | Recolour the whole glyph. |
| `tint_color` | colour | `"warning"` | `warning`, `error`, `success` or `"#rrggbb"`. |
| `glyph_color` | `"#rrggbb"` | `"#e1e1e1"` | Only used in full-colour mode (below). |

Colours are the theme's **symbolic classes**, so the panel picks the actual shade and the icon keeps
matching its neighbours in every theme. A `"#rrggbb"` value anywhere switches the icon to
**full-colour mode**: repotray renders an SVG with literal colours to
`~/.cache/repotray/icon-<hash>.svg` and the panel shows it as-is (no recolouring). Untinted parts
then use `glyph_color` — set it to your panel's text colour, e.g. `"#2e3436"` on a light panel.

The icon also has two fixed states that take precedence: **error** (a red cross: every fetch
failed, probably offline, or git is missing) and **paused** (two bars: fetching paused).

### Recipes

*Default* — a green ▲ when you have commits to push, an orange ▼ when someone else pushed, both
when both:

```toml
[indicator]
label = ["push", "pull"]
marker = "arrow"
top_dot = ["push"]
bottom_dot = ["pull"]
```

*Like mintupdate* — a single orange dot bottom-right whenever anything needs doing,
indistinguishable in style from the update icon next to it:

```toml
[indicator]
marker = "dot"
top_dot = []
bottom_dot = ["push", "pull", "dirty"]
```

*Quiet* — no numbers, no dots; the glyph itself turns orange when anything needs doing:

```toml
[indicator]
label = []
top_dot = []
bottom_dot = []
tint = ["push", "pull", "dirty"]
```

## `[repo."<path>"]` — per repository

```toml
[repo."~/work/huge-monorepo"]
fetch = false          # never fetch this one automatically (manual Fetch now still works)
name = "monorepo"      # display name
```

| Key | Type | Default | Notes |
|---|---|---|---|
| `[repo."<path>"] fetch` | bool | `true` | Include in automatic fetch passes. |
| `[repo."<path>"] name` | string | — | Display name; otherwise the directory name, `parent/name` when two collide. |

## Environment variables

| Variable | Effect |
|---|---|
| `REPOTRAY_CONFIG` | Config file path (the `--config` option wins). |
| `REPOTRAY_BACKEND` | Backend name (the `--backend` option wins over it, it wins over the config). |
| `GIT_SSH_COMMAND` | Respected if set; otherwise repotray uses `ssh -oBatchMode=yes`. |
