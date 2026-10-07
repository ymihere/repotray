"""Toolkit-free text for dialogs, shared by the GTK and Qt front ends."""

from __future__ import annotations

import datetime
import time

# The dialog button that brings incoming commits in, by the model's action name.
ACTION_LABELS = {"pull": "Pull", "sync": "Sync"}
NO_INCOMING_TEXT = "Nothing to pull (as of the last fetch)."


def more_commits_text(more: int) -> str:
    return f"… and {more} more. “Open in editor” shows all of them."


def commit_epoch(iso: str) -> float | None:
    """Seconds since the epoch of a commit's ISO-8601 date, or None if it does not parse."""
    try:
        return datetime.datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def details_text(result) -> str:
    """The Details dialog of an ActionResult: commands, exit status and full output."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result.started_at))
    lines = [
        f"{result.name}: {result.action.value} {'succeeded' if result.ok else 'failed'}",
        f"started {when}, took {result.duration:.1f} s",
    ]
    if result.restored is True:
        lines.append("The repository was restored to its previous state.")
    elif result.restored is False:
        lines.append("WARNING: the repository was NOT restored — inspect it before continuing.")
    lines.append("")
    lines.append(f"Message: {result.message}")
    for cmd in result.command:
        lines.append(f"$ {cmd}")
    if result.stdout.strip():
        lines += ["", "--- stdout ---", result.stdout.rstrip()]
    if result.stderr.strip():
        lines += ["", "--- stderr ---", result.stderr.rstrip()]
    return "\n".join(lines)


def blocked_text(label: str, tooltip: str) -> str:
    """Shown in a dialog when its action button is disabled (disabled buttons may hide tooltips)."""
    return f"{label} is not possible right now: {tooltip}"
