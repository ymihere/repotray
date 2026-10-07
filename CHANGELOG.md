# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- The tray icon's corner markers are now arrows: a ▲ top-right when there is something to push,
  a ▼ bottom-right when there is something to pull. `[indicator] marker = "dot"` restores the
  Mint-style dots.
- The panel shows one row per repository (push side left, pull side right), sorted by name;
  `panel_sort = "state"` lists syncable, then pushable, then pullable repositories first.
- The gear menu moved to the panel header.

### Added
- *Push all* and *Pull all* buttons next to *Sync all*, at the top of the panel, in the fallback
  menu, and as `repotray push --all` / `repotray pull --all`.

## [0.1.0] — unreleased

### Added
- Tray indicator for all local git clones: counts of repositories to push and to pull in the label,
  corner dots and an optional tint on a symbolic icon (Octicon `repo`) recoloured by the panel.
- Panel (Linux, GTK 3): pushable repos left, pullable right, Push / Pull / Sync buttons, Sync all,
  groups for uncommitted, no-upstream, detached, in-progress and failed repositories, result banner
  with details.
- Push (`git push` to the upstream), Pull (`--ff-only`), Sync (`pull --rebase` or merge, then push)
  with conflict abort and restore check.
- Background status (every minute) and fetch (every 10 minutes) passes with backoff when offline,
  pause, resume-from-suspend detection and automatic config reload.
- Backends: XApp (Cinnamon, MATE, Xfce), AppIndicator, Gtk.StatusIcon, pystray (experimental on
  macOS and Windows); third-party backends via the `repotray.backends` entry point.
- CLI: `status`, `scan`, `fetch`, `push`, `pull`, `sync`, `doctor`, `config`, `autostart`,
  `icons`, `quit`, and `--demo`.
- `scripts/install.sh` / `scripts/uninstall.sh` for Linux without pip.
