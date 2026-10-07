# Command line

```
repotray [GLOBAL OPTIONS] [COMMAND] [ARGS]
```

Global options (before or after the command): `--config PATH`, `-v/--verbose` (debug output on
stderr), `--backend NAME`, `--version`.

Without a command, `repotray` starts the tray. The CLI never imports a GUI toolkit except for
`tray`, so every other command works over SSH or in a container. CLI commands do not take the tray's
single-instance lock and may run while the tray runs.

On Windows, `repotrayw` is the same program without a console window: use it to start the tray
(`repotray` would keep its console window open while the tray runs). Output written to a pipe or
file is UTF-8 there, so the table's `↑`/`↓` survive redirection.

`REPO` arguments accept a display name (as shown by `scan`/`status`), a directory basename or a
path. A path to a repository outside the configured roots works too. When a name matches several
repositories, the candidates are listed and nothing runs (exit 2).

## Commands

| Command | Behaviour | Exit status |
|---|---|---|
| `repotray` / `repotray tray [--demo]` | Start the tray. `--demo` shows fabricated repositories and simulated actions. A second instance prints `repotray is already running (pid N)` and exits. | 0 |
| `repotray status [--json] [--demo]` | Scan, one status pass, print a table (or JSON). No network. | 0; 2 config error |
| `repotray scan [--absolute]` | List discovered repositories, `~`-abbreviated unless `--absolute`. | 0 |
| `repotray fetch [REPO…]` | Fetch all (or the given) repositories, then print the status table. | 0; 1 if any fetch failed; 2 usage |
| `repotray push [--all \| REPO…]` | `git push` the current branch to its upstream. `--all` = *Push all*: every repo that is only ahead (diverged ones are listed as skipped). | 0; 1 failed; 2 usage |
| `repotray pull [--all \| REPO…]` | `git pull --ff-only`. `--all` = *Pull all*: every repo that is only behind. | 0; 1 failed; 2 usage |
| `repotray sync [--all \| REPO…]` | Per repository: push if only ahead, pull if only behind, pull --rebase (or merge) then push if diverged; nothing if in sync. `--all` = *Sync all*. | 0; 1 failed; 2 usage |
| `repotray doctor` | Version, Python, platform and desktop, git, config path and warnings, roots and repository count, icon installation, autostart, log path, and every backend with its probe score (`*` = selected). | 0 |
| `repotray config path` | Print the config file path. | 0 |
| `repotray config default` | Print the default config (fully commented). | 0 |
| `repotray autostart enable\|disable\|status` | Linux: `~/.config/autostart/repotray.desktop`; macOS: `~/Library/LaunchAgents/io.github.repotray.plist`; Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `repotray`, which starts `repotrayw.exe tray` (no console window; `pythonw -m repotray tray` if the launcher is missing). | 0 |
| `repotray icons install\|uninstall` | Copy the symbolic icons into `~/.local/share/icons/hicolor/scalable/status/` (Linux; the tray does this at startup anyway) or remove the ones it copied. | 0 |
| `repotray quit` | Stop the running tray (SIGTERM to the pid in the instance lock). Not supported on Windows. | 0; 1 none running |

Action results print one line per repository, `ok` on stdout or `FAIL` on stderr, e.g.
`FAIL sync  notes: Commit or stash first`. With `--all`, repositories that are left out print a
`skip` line with the reason (uncommitted changes, diverged, operation in progress) and do not make
the command fail. With `-v`, failures also print the git commands and
their output.

## Status table

```
NAME           BRANCH  ↑  ↓  STATE              PATH
api-gateway    main    3  0  push,dirty         ~/code/api-gateway
design-system  main    2  2  diverged           ~/code/design-system
scratch        wip     -  -  dirty,no upstream  ~/code/scratch
```

`STATE` is a comma list of `push`, `pull`, `diverged`, `dirty`, `detached`, `no upstream`,
`upstream gone`, an operation in progress (`rebase`, `merge`, `cherry-pick`, `revert`, `bisect`),
`fetch failed`, `error`, or `clean`. `↑`/`↓` are `-` without an upstream.

## JSON schema (`repotray status --json`)

```json
{
  "version": 1,
  "generated_at": "2026-10-07T07:13:24.078240+00:00",
  "counts": {
    "push": 3, "pull": 3, "dirty": 3, "diverged": 1,
    "no_upstream": 2, "detached": 0, "fetch_failed": 1, "total": 11
  },
  "repos": [
    {
      "path": "/home/you/code/api-gateway",
      "name": "api-gateway",
      "branch": "main",
      "upstream": "origin/main",
      "ahead": 3,
      "behind": 0,
      "staged": 0,
      "unstaged": 2,
      "untracked": 0,
      "unmerged": 0,
      "dirty": true,
      "detached": false,
      "no_upstream": false,
      "upstream_gone": false,
      "operation": null,
      "fetch_error": null,
      "status_error": null
    }
  ]
}
```

- `version` changes only on incompatible changes.
- Counts are **repositories**, not commits. `push` counts repositories that can be pushed (plus
  branches without upstream when `count_no_upstream_as_push = true`); `diverged` ones are counted in
  both `push` and `pull`.
- `branch` is `null` when detached; `upstream` is `null` without one.
- `fetch_error` is always `null` from `status` (it does not fetch); `fetch` reports failures on
  stderr.
- `dirty` honours `count_untracked_as_dirty`.
