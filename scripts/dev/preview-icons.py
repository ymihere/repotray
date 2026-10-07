#!/usr/bin/env python3
"""Render a contact sheet of every tray icon variant, recoloured the way a panel does it.

Uses GTK's own symbolic loader (Gtk.IconInfo.load_symbolic), on a dark panel (#303036, fg #e1e1e1)
and a light one (#f6f6f6, fg #2e3436), at 16, 24 and 32 px.

    scripts/dev/preview-icons.py [-o icons-preview.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from repotray.icons import symbolic_dir  # noqa: E402

SIZES = (16, 24, 32)
THEMES = (
    ("dark", "#303036", "#e1e1e1"),
    ("light", "#f6f6f6", "#2e3436"),
)
# libst / Adwaita-like theme colours; real panels use their own.
SUCCESS, WARNING, ERROR = "#33d17a", "#f27835", "#e01b24"
DOTS = (None, "foreground", "warning", "error", "success")
TINTS = (None, "warning", "error", "success")
CELL_W, CELL_H, LABEL_W, HEAD_H = 110, 40, 170, 30


def rgba(hex_color: str) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


def name(tint, top, bottom) -> str:
    n = "repotray"
    if tint:
        n += f"-tint-{tint}"
    if top:
        n += f"-top-{top}"
    if bottom:
        n += f"-bottom-{bottom}"
    return n + "-symbolic"


def load(icon: str, size: int, fg: str):
    path = symbolic_dir() / f"{icon}.svg"
    theme = Gtk.IconTheme.get_default()
    info = theme.lookup_by_gicon(Gio.FileIcon.new(Gio.File.new_for_path(str(path))), size, 0)
    pixbuf, _ = info.load_symbolic(rgba(fg), rgba(SUCCESS), rgba(WARNING), rgba(ERROR))
    return pixbuf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="icons-preview.png")
    args = ap.parse_args()

    rows = [(t, top, b) for top in DOTS for b in DOTS for t in (None,)]
    extra = ["repotray-error-symbolic", "repotray-paused-symbolic"]
    n_rows = len(rows) + 1
    sheet_w = LABEL_W + CELL_W * len(TINTS)
    width = sheet_w * len(THEMES)
    height = HEAD_H + CELL_H * n_rows
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(10)

    for ti, (theme_name, bg, fg) in enumerate(THEMES):
        x0 = ti * sheet_w
        cr.set_source_rgb(*[c / 255 for c in bytes.fromhex(bg[1:])])
        cr.rectangle(x0, 0, sheet_w, height)
        cr.fill()
        fgc = [c / 255 for c in bytes.fromhex(fg[1:])]
        cr.set_source_rgb(*fgc)
        cr.move_to(x0 + 6, 18)
        cr.show_text(f"{theme_name} · columns: tint none/warning/error/success")
        for ri, (_, top, bottom) in enumerate(rows):
            y = HEAD_H + ri * CELL_H
            cr.set_source_rgb(*fgc)
            cr.move_to(x0 + 6, y + 24)
            cr.show_text(f"top={top or '-'} bottom={bottom or '-'}")
            for ci, tint in enumerate(TINTS):
                x = x0 + LABEL_W + ci * CELL_W
                for size in SIZES:
                    pb = load(name(tint, top, bottom), size, fg)
                    Gdk.cairo_set_source_pixbuf(cr, pb, x, y + (CELL_H - size) / 2)
                    cr.paint()
                    x += size + 6
        y = HEAD_H + len(rows) * CELL_H
        cr.set_source_rgb(*fgc)
        cr.move_to(x0 + 6, y + 24)
        cr.show_text("error · paused")
        x = x0 + LABEL_W
        for icon in extra:
            for size in SIZES:
                pb = load(icon, size, fg)
                Gdk.cairo_set_source_pixbuf(cr, pb, x, y + (CELL_H - size) / 2)
                cr.paint()
                x += size + 6
            x += 20
    surface.write_to_png(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
