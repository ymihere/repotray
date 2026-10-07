from pathlib import Path

import pytest

from repotray.core.gitrun import CallKind, GitResult
from repotray.core.gitstatus import check_status, detect_operation, parse_porcelain_v2
from repotray.core.types import RepoInfo

OID = "1" * 40
HDR = f"# branch.oid {OID}\0# branch.head main\0"
UP = "# branch.upstream origin/main\0"


def ab(a, b):
    return f"# branch.ab +{a} -{b}\0"


def entry1(xy, path):
    return f"1 {xy} N... 100644 100644 100644 {OID} {OID} {path}\0"


def entry2(xy, path, orig):
    return f"2 {xy} N... 100644 100644 100644 {OID} {OID} R100 {path}\0{orig}\0"


def parse(s: str):
    return parse_porcelain_v2(s.encode())


def test_clean():
    st = parse(HDR + UP + ab(0, 0))
    assert (st.branch, st.oid, st.upstream, st.ahead, st.behind) == (
        "main",
        OID,
        "origin/main",
        0,
        0,
    )
    assert st.has_ab and not st.detached
    assert st.staged == st.unstaged == st.untracked == st.unmerged == 0


def test_staged_unstaged_untracked_unmerged():
    data = (
        HDR
        + UP
        + ab(0, 0)
        + entry1("M.", "a")
        + entry1(".M", "b")
        + entry1("MM", "c")
        + "? new.txt\0"
        + f"u UU N... 100644 100644 100644 100644 {OID} {OID} {OID} conflict\0"
        + "! ignored\0"
    )
    st = parse(data)
    assert st.staged == 2
    assert st.unstaged == 2
    assert st.untracked == 1
    assert st.unmerged == 1


def test_untracked_only():
    st = parse(HDR + UP + ab(0, 0) + "? x\0? y\0")
    assert st.untracked == 2 and st.staged == st.unstaged == 0


@pytest.mark.parametrize(("a", "b"), [(3, 0), (0, 4), (2, 5)])
def test_ahead_behind(a, b):
    st = parse(HDR + UP + ab(a, b))
    assert (st.ahead, st.behind) == (a, b)


def test_no_upstream():
    st = parse(HDR)
    assert st.upstream is None and not st.has_ab


def test_upstream_gone():
    st = parse(HDR + UP)
    assert st.upstream == "origin/main" and not st.has_ab


def test_detached():
    st = parse(f"# branch.oid {OID}\0# branch.head (detached)\0")
    assert st.detached and st.branch is None


def test_initial_commit():
    st = parse("# branch.oid (initial)\0# branch.head main\0? a\0")
    assert st.oid is None and st.branch == "main" and st.untracked == 1


def test_rename_with_tricky_original_paths():
    # The original path of a rename is a separate NUL field; it must never be parsed as a record.
    data = HDR + UP + ab(0, 0) + entry2("R.", "new", "1 old") + entry2("R.", "n2", "? weird")
    st = parse(data)
    assert st.staged == 2
    assert st.untracked == 0
    assert (st.ahead, st.behind) == (0, 0)


def test_rename_original_looks_like_header():
    st = parse(HDR + UP + ab(1, 0) + entry2("R.", "x", "# branch.ab +7 -7"))
    assert (st.ahead, st.behind) == (1, 0)
    assert st.staged == 1


def test_paths_with_spaces_and_hash():
    st = parse(HDR + entry1(".M", "dir/# not a header") + "? 1 not a record\0")
    assert st.unstaged == 1 and st.untracked == 1


def test_stash_header_ignored():
    st = parse(HDR + UP + ab(0, 0) + "# stash 3\0")
    assert st.ahead == 0


def test_detect_operation(tmp_path: Path):
    assert detect_operation(tmp_path) is None
    (tmp_path / "rebase-merge").mkdir()
    assert detect_operation(tmp_path) == "rebase"
    (tmp_path / "rebase-merge").rmdir()
    (tmp_path / "MERGE_HEAD").write_text("x")
    assert detect_operation(tmp_path) == "merge"
    (tmp_path / "MERGE_HEAD").unlink()
    (tmp_path / "CHERRY_PICK_HEAD").write_text("x")
    assert detect_operation(tmp_path) == "cherry-pick"


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, cwd, timeout, *, kind):
        self.calls.append((tuple(args), kind))
        for prefix, res in self.responses:
            if tuple(args[: len(prefix)]) == prefix:
                return res
        return GitResult(1, b"", b"fatal: unexpected", False, tuple(args))


def ok(out: bytes | str) -> GitResult:
    return GitResult(0, out.encode() if isinstance(out, str) else out, b"", False, ())


def test_check_status_reads_upstream_config(tmp_path):
    info = RepoInfo(tmp_path, tmp_path / ".git", "r")
    runner = FakeRunner(
        [
            (("status",), ok(HDR + UP + ab(2, 1))),
            (("config",), ok("branch.main.remote origin\nbranch.main.merge refs/heads/main\n")),
        ]
    )
    st = check_status(runner, info, now=5.0)
    assert st.upstream_remote == "origin" and st.upstream_merge == "refs/heads/main"
    assert st.ahead == 2 and st.behind == 1 and st.diverged
    assert runner.calls[0][1] is CallKind.STATUS
    assert "--untracked-files=normal" in runner.calls[0][0]


def test_check_status_error(tmp_path):
    info = RepoInfo(tmp_path, tmp_path / ".git", "r")
    runner = FakeRunner(
        [(("status",), GitResult(128, b"", b"fatal: not a git repository", False, ()))]
    )
    st = check_status(runner, info, count_untracked=False)
    assert st.status_error == "not a git repository"
    assert "--untracked-files=no" in runner.calls[0][0]
