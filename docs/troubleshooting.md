# Troubleshooting

Start with `repotray doctor`: it shows the config file and its warnings, how many repositories were
found, which tray backend is used and why, and whether the icons are installed. The tray logs to
`~/.local/state/repotray/repotray.log`; run `repotray tray -v` to also see the log in the terminal.

## The icon does not appear, or appears as a blank/generic square

- `repotray doctor` → *icons*. They should be in `~/.local/share/icons/hicolor/scalable/status/`
  (or system-wide). Run `repotray icons install` and restart the tray.
- On Cinnamon, the *XApp Status Applet* must be in the panel (it is by default). `doctor` should
  show `xapp` with score 100. A score of 30 means no applet is listening.
- On GNOME, install and enable the *AppIndicator and KStatusNotifierItem Support* extension and
  `gir1.2-ayatanaappindicator3-0.1`; repotray then uses the `appindicator` backend.
- Force a backend with `repotray tray --backend appindicator` (or `backend = "…"` in the config) to
  compare.

## The counts next to the icon show only "…" (Cinnamon)

Cinnamon's XApp Status Applet shortens a label to "…" when the panel gives it even a fraction of
a pixel less than it asked for. That happens when another applet in the same panel zone reports a
fractional width (for example *multicore-sys-monitor*): the panel rounds the zone down and takes the
missing pixel from the label. repotray cannot work around it; the label text is all it controls
([linuxmint/cinnamon#14096](https://github.com/linuxmint/cinnamon/issues/14096)).

- Move the applet with the fractional width to another zone of the panel, or
- install a fixed copy of the XApp applet as a user override (Cinnamon prefers it to the system
  copy; delete it again once your Cinnamon includes the fix):

  ```sh
  cp -r /usr/share/cinnamon/applets/xapp-status@cinnamon.org ~/.local/share/cinnamon/applets/
  cd ~/.local/share/cinnamon/applets/xapp-status@cinnamon.org
  sed -i 's|^const St = imports.gi.St;|&\nconst Pango = imports.gi.Pango;|' applet.js
  sed -i "/'y-align': St.Align.END,/{n;s|$|\n        this.label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;|}" applet.js
  dbus-send --session --dest=org.Cinnamon --type=method_call /org/Cinnamon \
      org.Cinnamon.ReloadXlet string:xapp-status@cinnamon.org string:APPLET
  ```

## The icon is not recoloured like the others

Symbolic recolouring only works with theme colour names. If any `[indicator]` colour is a
`#rrggbb` value, repotray switches to full-colour icons on purpose; set `glyph_color` to your panel's
text colour, or use `foreground` / `warning` / `error` / `success` instead.

## The panel opens in the wrong place

On Cinnamon the applet reports the icon position, so the panel sits above (or below) it. Other
backends do not know where the icon is and open it at the mouse pointer. **Wayland** does not let
applications position their own windows, so on Wayland the panel opens wherever the compositor
puts it; use the right-click menu or the panel's contents in the menu instead.

## A push or pull asks for a password / fails with "could not read Username"

repotray never prompts (it runs git with `GIT_TERMINAL_PROMPT=0` and SSH in batch mode), so a
remote that needs interactive credentials fails fast. Fix it in git, once, in a terminal:

- HTTPS: configure a credential helper (`git config --global credential.helper libsecret` or
  `cache`), then pull once in a terminal so it is stored.
- SSH: load your key into an agent (`ssh-add`) that the desktop session shares; with a passphrase,
  use the desktop's keyring agent.

## Sync stops on a GPG/SSH signing prompt (pinentry)

If you sign commits (`commit.gpgsign = true`), a rebase re-signs the rebased commits and may pop up
pinentry. That is your git configuration at work; repotray does not work around it. Unlock the key
first, use `sync_strategy = "merge"` (the merge commit is signed once), or sync in a terminal. If
signing fails, the rebase is aborted and the repository restored.

## "Commit or stash first"

Sync refuses to run while the repository has uncommitted changes to tracked files, because a
rebase over them could leave a mess. Untracked files do not block it. Commit or stash, then Sync.

## "Not possible to fast-forward"

Pull only fast-forwards. The branch has local commits too — the row should show *Sync* instead;
if the state was stale, the next status pass (or *Fetch now*) fixes the display.

## The tray shows the error icon (red cross)

Every fetch in the last pass failed — usually no network — or git is missing. repotray retries with
growing intervals (up to an hour); *Fetch all now* retries immediately. The panel header says
which; `repotray fetch` in a terminal shows each error.

## Repositories are missing

Check `roots`, `max_depth` (default 4 levels below each root), `exclude_dirs` and `ignore` with
`repotray scan`. Hidden directories are never searched below a root; add them as a root or under
`repos`. Repositories inside other repositories are skipped unless `descend_into_repos = true`.

## Lots of CPU or disk activity

Status checks are cheap but scale with the number and size of repositories. Raise
`status_interval`, lower `workers`, add huge repositories to `ignore`, or set
`[repo."<path>"] fetch = false` for repositories you rarely pull.

## "repotray is already running"

Only one tray runs per user. `repotray quit` stops it.
