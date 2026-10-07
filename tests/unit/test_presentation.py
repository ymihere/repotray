"""Indicator, panel model, menus and tooltip: pure functions of (snapshot, config, now)."""

from dataclasses import replace
from pathlib import Path

import pytest

from repotray.core.config import Config, IndicatorConfig
from repotray.core.demo import demo_snapshot
from repotray.core.indicator import IconSpec, counts, icon_spec, label_text
from repotray.core.model import (
    MenuItem,
    UiState,
    ago,
    build_banner,
    control_menu,
    fallback_menu,
    panel_model,
)
from repotray.core.tooltip import tooltip_text
from repotray.core.types import (
    ActionKind,
    ActionResult,
    FetchMode,
    RepoInfo,
    RepoState,
    Snapshot,
)

NOW = 1_800_000_000.0


def st(name, **kw) -> RepoState:
    p = Path("/r") / name
    base = dict(branch="main", upstream="origin/main", upstream_remote="origin",
                upstream_merge="refs/heads/main")  # fmt: skip
    base.update(kw)
    return RepoState(info=RepoInfo(p, p / ".git", name), **base)


def snap(*states, **kw) -> Snapshot:
    kw.setdefault("last_fetch_pass_at", NOW - 180)
    return Snapshot(repos=tuple(states), generated_at=NOW, **kw)


DEMO = demo_snapshot(NOW)


# --- indicator ------------------------------------------------------------------------------------


def test_demo_label_and_icon():
    cfg = Config()
    assert label_text(DEMO, cfg) == "↑3 ↓3"
    # Both markers in the pull marker's orange (the green was hard to see).
    assert icon_spec(DEMO, cfg) == IconSpec("attention", "warning", "warning", None)
    assert icon_spec(DEMO, cfg).marker == "arrow"
    dots = Config(indicator=IndicatorConfig(marker="dot"))
    assert icon_spec(DEMO, dots).marker == "dot"


def test_label_parts_order_and_zero_omission():
    cfg = Config(indicator=IndicatorConfig(label=("dirty", "pull", "push")))
    s = snap(st("a", ahead=1), st("b", unstaged=1))
    assert label_text(s, cfg) == "✎1 ↑1"
    assert label_text(s, Config(indicator=IndicatorConfig(label=()))) == ""
    assert label_text(snap(st("c")), Config()) == ""


def test_dot_and_tint_triggers():
    s = snap(st("a", unstaged=1))
    assert icon_spec(s, Config()).state == "clean"
    ind = IndicatorConfig(top_dot=(), bottom_dot=("push", "pull", "dirty"), tint=("dirty",))
    spec = icon_spec(s, Config(indicator=ind))
    assert spec == IconSpec("attention", None, "warning", "warning")


def test_count_no_upstream_as_push():
    s = snap(st("a", upstream=None, upstream_remote=None, upstream_merge=None))
    assert counts(s, Config()).push == 0
    cfg = Config(count_no_upstream_as_push=True)
    assert counts(s, cfg).push == 1
    assert icon_spec(s, cfg).top == "warning"


def test_untracked_counting():
    s = snap(st("a", untracked=2))
    assert counts(s, Config()).dirty == 1
    assert counts(s, Config(count_untracked_as_dirty=False)).dirty == 0


def test_error_beats_paused_beats_attention():
    base = snap(st("a", ahead=1))
    paused = replace(base, fetch_mode=FetchMode.PAUSED)
    assert icon_spec(paused, Config()).state == "paused"
    err = replace(paused, all_fetches_failed=True)
    assert icon_spec(err, Config()).state == "error"
    assert icon_spec(replace(base, git_missing=True), Config()).state == "error"
    assert label_text(err, Config()) == "↑1"  # label kept in error state


def test_hex_mode_flag():
    ind = IndicatorConfig(top_dot_color="#ff0000")
    assert icon_spec(snap(st("a", ahead=1)), Config(indicator=ind)).hex_mode
    assert not icon_spec(snap(st("a", ahead=1)), Config()).hex_mode


# --- panel model ----------------------------------------------------------------------------------


def row_tuples(m):
    return [
        (r.left.name if r.left else None, bool(r.sync), r.right.name if r.right else None)
        for r in m.rows
    ]


def test_demo_rows():
    m = panel_model(DEMO, Config(), NOW)
    assert m.columns_title == ("Push (3)", "Pull (3)")
    # One repo per row, alphabetical; push cells left, pull cells right, sync when diverged.
    assert row_tuples(m) == [
        ("api-gateway", False, None),
        ("design-system", True, "design-system"),
        ("infra", False, None),
        (None, False, "mobile-app"),
        (None, False, "website"),
    ]
    shared = m.rows[1]
    assert not shared.left.button.enabled and shared.left.button.tooltip == "Diverged — use Sync"
    assert not shared.right.button.enabled
    assert shared.sync.enabled and shared.sync.tooltip == "Sync: pull --rebase, then push"
    api = m.rows[0].left
    assert api.count_text == "↑3" and api.dirty
    assert api.button.enabled and api.button.tooltip == "Push 3 commits to origin/main"
    assert m.rows[4].right.button.tooltip == "Pull 4 commits from origin/main (fast-forward)"


def test_rows_sorted_by_state():
    m = panel_model(DEMO, Config(panel_sort="state"), NOW)
    assert row_tuples(m) == [
        ("design-system", True, "design-system"),
        ("api-gateway", False, None),
        ("infra", False, None),
        (None, False, "mobile-app"),
        (None, False, "website"),
    ]
    assert m.empty_text is None
    assert m.header.summary == "7 repos need attention"
    assert m.header.fetched_text == "Fetched 3 min ago"


def test_demo_groups():
    m = panel_model(DEMO, Config(), NOW)
    groups = {g.kind: g for g in m.groups}
    assert [g.kind for g in m.groups] == ["dirty", "no_upstream", "fetch_failed", "in_sync"]
    assert [c.name for c in groups["dirty"].chips] == ["api-gateway", "notes", "scratch"]
    assert [c.name for c in groups["no_upstream"].chips] == ["experiments", "scratch"]
    assert "Could not resolve host" in groups["fetch_failed"].chips[0].tooltip
    assert groups["in_sync"].collapsed
    assert [c.name for c in groups["in_sync"].chips] == ["docs", "dotfiles"]


def test_sync_disabled_when_dirty_and_merge_tooltip():
    s = snap(st("d", ahead=1, behind=1, staged=1))
    m = panel_model(s, Config(sync_strategy="merge"), NOW)
    assert m.rows[0].sync.tooltip == "Commit or stash first" and not m.rows[0].sync.enabled
    s2 = snap(st("d", ahead=1, behind=1, untracked=3))
    m2 = panel_model(s2, Config(sync_strategy="merge"), NOW)
    assert m2.rows[0].sync.enabled and m2.rows[0].sync.tooltip == "Sync: merge, then push"


def test_operation_in_progress_blocks():
    s = snap(st("o", ahead=2, operation="rebase"))
    m = panel_model(s, Config(), NOW)
    assert m.rows[0].left.button.tooltip == "Operation in progress: rebase"
    assert any(g.kind == "in_progress" for g in m.groups)


def test_local_upstream_has_no_push():
    s = snap(st("l", ahead=2, upstream_remote="."))
    m = panel_model(s, Config(), NOW)
    assert not m.rows[0].left.button.enabled


def test_busy_buttons():
    a = st("a", ahead=1, behind=1)
    s = snap(a, running={a.path: ActionKind.SYNC})
    row = panel_model(s, Config(), NOW).rows[0]
    assert row.sync.busy and not row.sync.enabled
    assert not row.left.button.busy and row.left.button.tooltip == "Busy: syncing…"


def test_rows_one_repo_each_case_insensitive():
    s = snap(st("b", ahead=1), st("A", ahead=1), st("Z", behind=1), st("c"))
    assert row_tuples(panel_model(s, Config(), NOW)) == [
        ("A", False, None),
        ("b", False, None),
        (None, False, "Z"),
    ]


def test_empty_state_and_summary():
    m = panel_model(snap(st("a"), st("b")), Config(), NOW)
    assert m.rows == () and m.empty_text == "Nothing to push or pull"
    assert m.header.summary == "All 2 repos in sync"
    assert not m.bulk.sync.enabled and not m.bulk.push.enabled and not m.bulk.pull.enabled


def test_header_states():
    base = snap(st("a"))
    assert panel_model(replace(base, fetch_mode=FetchMode.FETCHING), Config(), NOW).header.fetching
    off = replace(base, all_fetches_failed=True, next_fetch_at=NOW + 480)
    h = panel_model(off, Config(), NOW).header
    assert h.summary == "Offline — fetch failed for every repo, retrying in 8 min" and h.error
    p = panel_model(replace(base, fetch_mode=FetchMode.PAUSED), Config(), NOW).header
    assert p.summary == "Fetching paused" and p.paused
    assert panel_model(
        replace(base, last_fetch_pass_at=None), Config(), NOW
    ).header.fetched_text == ("Never fetched")


def test_bulk_buttons():
    b = panel_model(DEMO, Config(), NOW).bulk
    assert (b.push.label, b.sync.label, b.pull.label) == ("Push all", "Sync all", "Pull all")
    assert b.push.enabled and b.sync.enabled and b.pull.enabled
    assert b.push.tooltip.startswith("Push 2 repos: api-gateway, infra; skips design-system")
    assert b.pull.tooltip.startswith("Pull 2 repos: mobile-app, website")
    assert "push 2" in b.sync.tooltip and "sync 1" in b.sync.tooltip
    running = panel_model(replace(DEMO, bulk=(ActionKind.SYNC, 2, 5)), Config(), NOW).bulk
    assert running.sync.label == "Syncing 2/5…" and running.sync.busy
    assert not running.push.enabled and "Sync all is running" in running.push.tooltip
    pushing = panel_model(replace(DEMO, bulk=(ActionKind.PUSH, 0, 2)), Config(), NOW).bulk
    assert pushing.push.label == "Pushing 0/2…" and not pushing.pull.enabled


def result(ok, end, name="api-gateway", action=ActionKind.PUSH, msg="x"):
    return ActionResult(
        Path("/r") / name, action, ok, msg, started_at=end - 1, duration=1, name=name
    )


def test_banner_timing():
    s = replace(DEMO, recent_results=(result(True, NOW - 2),))
    b = build_banner(s, NOW, 0)
    assert b.kind == "success" and b.text == "Pushed api-gateway" and b.expires_at == NOW + 4
    assert build_banner(s, NOW + 5, 0) is None
    fail = replace(DEMO, recent_results=(result(False, NOW - 100, msg="rejected"),))
    b = build_banner(fail, NOW, 0)
    assert b.kind == "error" and b.text == "api-gateway: rejected"
    assert build_banner(fail, NOW, ack=NOW) is None


def test_failed_action_marks_row():
    a = st("a", ahead=1)
    s = snap(a, recent_results=(result(False, NOW, name="a", msg="push rejected"),))
    assert panel_model(s, Config(), NOW).rows[0].left.warning == "push rejected"


def test_ago():
    assert ago(NOW - 10, NOW) == "just now"
    assert ago(NOW - 180, NOW) == "3 min ago"
    assert ago(NOW - 7300, NOW) == "2 h ago"
    assert ago(None, NOW) == "never"


# --- menus ----------------------------------------------------------------------------------------


def labels(items):
    return [i.label for i in items if not i.separator]


def test_repo_menu_offers_incoming_commits_when_behind():
    m = panel_model(DEMO, Config(), NOW)
    by = {}
    for r in m.rows:
        for c in (r.left, r.right):
            if c:
                by[(c.name, c is r.left)] = c.menu
    website = [i.label for i in by[("website", False)] if not i.separator]
    assert website[0] == "Show incoming commits (4)…"
    assert by[("website", False)][0].action == "show_incoming"
    assert by[("design-system", True)][0].label == "Show incoming commits (2)…"
    api = [i.label for i in by[("api-gateway", True)]]
    assert not any("incoming" in label for label in api)
    assert api[0] == "Open terminal here"
    chips = {c.name: c.menu for g in m.groups for c in g.chips}
    assert chips["docs"][0].label == "Open terminal here"


def test_control_menu():
    items = control_menu(replace(DEMO, fetch_mode=FetchMode.PAUSED), UiState(autostart=True))
    assert labels(items) == [
        "Fetch all now",
        "Pause fetching",
        "Rescan roots",
        "Open config file",
        "Autostart",
        "About",
        "Quit",
    ]
    by = {i.label: i for i in items}
    assert by["Pause fetching"].checked is True and by["Autostart"].checked is True


def test_fallback_menu():
    items = fallback_menu(DEMO, Config(), NOW, open_panel=True)
    ls = labels(items)
    assert ls[0] == "Open panel…"
    assert "Sync (1)" in ls and "Push (2)" in ls and "Pull (2)" in ls
    assert "Sync design-system  ↑2 ↓2" in ls
    assert "Push api-gateway  ↑3 ✎" in ls
    assert ls[-7:] == labels(control_menu(DEMO))
    bulk = {i.action: i for i in items if i.action in ("push_all", "pull_all", "sync_all")}
    assert [bulk[a].label for a in ("push_all", "pull_all", "sync_all")] == [
        "Push all",
        "Pull all",
        "Sync all",
    ]
    assert all(i.enabled for i in bulk.values())
    groups = [i for i in items if i.children]
    assert groups and all(isinstance(c, MenuItem) for g in groups for c in g.children)


# --- tooltip --------------------------------------------------------------------------------------


def test_tooltip_demo_plain():
    t = tooltip_text(DEMO, Config(), NOW)
    lines = t.splitlines()
    assert lines[0] == "Push (3)"
    assert lines[1].split() == ["design-system", "↑2"]  # diverged first
    assert lines[2].split() == ["api-gateway", "↑3", "✎"]
    assert "Pull (3)" in lines
    assert any(line.startswith("Uncommitted (3)") for line in lines)
    assert "No upstream (2): experiments, scratch" in lines
    assert lines[-1] == "Fetched 3 min ago"


def test_tooltip_markup_escapes():
    s = snap(st("<b>&evil", ahead=1))
    t = tooltip_text(s, Config(), NOW, markup=True)
    assert "&lt;b&gt;&amp;evil" in t and "<b>Push (1)</b>" in t


def test_tooltip_cap():
    many = [st(f"r{i:02}", ahead=1) for i in range(20)]
    t = tooltip_text(snap(*many), Config(), NOW)
    assert "… and 5 more" in t
    assert sum(1 for line in t.splitlines() if line.startswith("  r")) == 15


@pytest.mark.parametrize("limit", [127, 40])
def test_tooltip_char_limit(limit):
    t = tooltip_text(DEMO, Config(), NOW, max_chars=limit)
    assert len(t) <= limit and t.startswith("repotray:")
    assert "\n" not in t


def test_tooltip_all_clean_and_offline():
    assert tooltip_text(snap(st("a")), Config(), NOW).splitlines()[0] == "The repo is in sync"
    off = snap(st("a"), all_fetches_failed=True, next_fetch_at=NOW + 60)
    assert tooltip_text(off, Config(), NOW).startswith("Offline")
