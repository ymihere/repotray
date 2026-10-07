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
- The ▲ (push) marker is orange like the ▼ (pull) marker by default; the green was hard to see.
- *Open terminal here* opens the desktop's default terminal (Preferred Applications on
  Cinnamon/MATE/GNOME, then `xdg-terminals.list`) instead of the `x-terminal-emulator`
  alternative.

### Added
- **Windows: the panel.** New `qt` backend (Qt 6 via PySide6, now a Windows dependency instead
  of pystray): left click opens the same panel as on Linux above the tray icon, right click the
  control menu, middle click fetches; incoming-commits and details dialogs; follows the taskbar's
  dark/light setting; tray icon drawn for every size from 16 to 64 px.
- `repotrayw`: starts the tray without a console window on Windows; autostart uses it.
- *Push all* and *Pull all* buttons next to *Sync all*, at the top of the panel, in the fallback
  menu, and as `repotray push --all` / `repotray pull --all`.
- *Show incoming commits…* in a repository's menu: the commit messages a pull would bring, with
  *Open in editor* for the full log and a *Pull* button (*Sync* for diverged branches). New
  `editor` setting (default: the desktop's text editor), also used by *Open config file*.

### Fixed
- ssh remotes now use the repository's `core.sshCommand` (e.g. Windows' OpenSSH and its agent)
  with batch mode added; repotray used to replace it with plain `ssh`. `GIT_SSH` is respected.
- Windows: `repotray status`/`fetch`/`config default` no longer crash when their output goes to a
  pipe or file (UTF-8 instead of the ANSI code page).
- Windows: *Open terminal here* without Windows Terminal opened `cmd` hidden; it gets a window now.
- Windows: `terminal`/`file_manager`/`editor` templates keep a quoted program path with spaces.
- Windows: autostart no longer opens a console window at login.
- Windows: paths are shown as `~\code\x` instead of `~/code\x`.

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
