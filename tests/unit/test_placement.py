import pytest

from repotray.ui.placement import Anchor, Rect, monitor_for, place, side_from_position

# Primary 2560x1440 at x=1920 with a 40 px bottom panel; a laptop to the left; one to the right.
PRIMARY = (Rect(1920, 0, 2560, 1440), Rect(1920, 0, 2560, 1400))
LAPTOP = (Rect(0, 717, 1920, 1200), Rect(0, 717, 1920, 1200))
RIGHT = (Rect(4480, 0, 2560, 1440), Rect(4480, 0, 2560, 1440))
SIZE = (480, 350)


def test_bottom_panel_centred_on_icon():
    wa = PRIMARY[1]
    x, y = place(Anchor(4000, 1400, "bottom"), SIZE, wa)
    assert x == 4000 + 12 - 240
    assert y + SIZE[1] == wa.bottom


def test_top_panel():
    wa = Rect(0, 30, 1920, 1050)
    x, y = place(Anchor(900, 30, "top"), SIZE, wa)
    assert y == 30 and x == 900 + 12 - 240


def test_left_and_right_panels():
    wa = Rect(48, 0, 1872, 1080)
    x, y = place(Anchor(48, 500, "left"), SIZE, wa)
    assert x == 48 and y == 500 + 12 - 175
    wa = Rect(0, 0, 1872, 1080)
    x, y = place(Anchor(1872, 500, "right"), SIZE, wa)
    assert x + SIZE[0] == 1872


def test_clamped_at_monitor_edge():
    wa = PRIMARY[1]
    x, y = place(Anchor(4470, 1400, "bottom"), SIZE, wa)
    assert x + SIZE[0] == wa.right
    x, _ = place(Anchor(1925, 1400, "bottom"), SIZE, wa)
    assert x == wa.x


def test_no_anchor_and_pointer():
    wa = PRIMARY[1]
    assert place(None, SIZE, wa) == (wa.right - 480, wa.bottom - 350)
    x, y = place(Anchor(3000, 900, None), SIZE, wa)
    assert (x, y) == (3000 - 240, 900 - 350 - 4)
    x, y = place(Anchor(3000, 100, None), SIZE, wa)  # no room above → below
    assert y == 104


def test_window_larger_than_workarea():
    wa = Rect(0, 0, 400, 300)
    assert place(Anchor(10, 300, "bottom"), (480, 350), wa) == (0, 0)


def test_monitor_selection_with_offsets():
    mons = [PRIMARY, LAPTOP, RIGHT]
    assert monitor_for(Anchor(4100, 1400, "bottom"), mons) == PRIMARY[1]
    assert monitor_for(Anchor(500, 1000, "bottom"), mons) == LAPTOP[1]
    assert monitor_for(Anchor(5000, 10, "top"), mons) == RIGHT[1]
    assert monitor_for(Anchor(100, 100, None), mons) == LAPTOP[1]  # nearest: gap above the laptop
    assert monitor_for(None, mons) == PRIMARY[1]
    with pytest.raises(ValueError):
        monitor_for(None, [])


def test_side_from_gtk_position():
    assert [side_from_position(i) for i in range(4)] == ["left", "right", "top", "bottom"]
    assert side_from_position(9) is None
