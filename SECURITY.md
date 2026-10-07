# Security policy

## Reporting a vulnerability

Please report security problems privately via
[GitHub security advisories](https://github.com/ymihere/repotray/security/advisories/new), not in
public issues. You will get an answer within a week.

## Safety model

repotray runs git on many repositories unattended, so it is built to be harmless by default:

- **No modification without a click.** Background work is `git status` (read-only, with
  `GIT_OPTIONAL_LOCKS=0`) and `git fetch` (updates remote-tracking refs only). Push, pull and sync
  run only when the user presses a button or runs the CLI command.
- **No force, no stash.** Never `--force`, never `-u`, never auto-stash. Pull is `--ff-only`.
- **No prompts.** git runs with stdin closed, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`,
  `GIT_ASKPASS=true`, `SSH_ASKPASS_REQUIRE=never` and `ssh -oBatchMode=yes`, and editors disabled.
  repotray never sees, stores or asks for credentials.
- **No shell.** Commands are argument lists; terminal and file-manager templates are split before
  `{path}` is substituted, so repository paths cannot inject commands.
- **Restore on failure.** A sync that fails or times out aborts its rebase or merge and verifies
  that HEAD is unchanged.
- **Timeouts.** Every git call has a timeout; the whole process group is killed.
- **Logs** never contain credentials: `user:password@` is stripped from URLs in messages.

Hooks configured in your repositories (e.g. `pre-push`) do run on push, as with plain git.
