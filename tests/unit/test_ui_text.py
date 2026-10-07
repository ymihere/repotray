"""Toolkit-free dialog texts shared by the GTK and Qt front ends."""

from pathlib import Path

from repotray.core.types import ActionKind, ActionResult
from repotray.ui.text import blocked_text, commit_epoch, details_text, more_commits_text


def test_details_text():
    r = ActionResult(
        repo=Path("/r/x"),
        action=ActionKind.SYNC,
        ok=False,
        message="conflicts in README",
        command=("git pull --rebase", "git rebase --abort"),
        stderr="CONFLICT (content): README\n",
        started_at=0.0,
        duration=1.25,
        restored=True,
        name="x",
    )
    text = details_text(r)
    assert text.startswith("x: sync failed\nstarted ")
    assert "took 1.2 s" in text or "took 1.3 s" in text
    assert "restored to its previous state" in text
    assert "$ git pull --rebase\n$ git rebase --abort" in text
    assert text.endswith("--- stderr ---\nCONFLICT (content): README")


def test_commit_epoch_and_texts():
    assert commit_epoch("1970-01-01T00:01:00+00:00") == 60.0
    assert commit_epoch("yesterday") is None
    assert more_commits_text(3).startswith("… and 3 more.")
    assert blocked_text("Pull", "Diverged — use Sync") == (
        "Pull is not possible right now: Diverged — use Sync"
    )
