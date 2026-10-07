"""MenuItem models → QMenu."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QWidget


def literal(text: str) -> str:
    """Text for a Qt menu item or button: a single ``&`` would mark a keyboard mnemonic."""
    return text.replace("&", "&&")


def build_menu(
    items: Sequence, dispatch: Callable[[str, object], None], parent: QWidget | None = None
) -> QMenu:
    """Build a QMenu. ``dispatch(action, path)`` is called when an item is chosen."""
    menu = QMenu(parent)
    fill_menu(menu, items, dispatch)
    return menu


def fill_menu(menu: QMenu, items: Sequence, dispatch: Callable[[str, object], None]) -> None:
    """(Re)fill ``menu`` with ``items``; submenus of an earlier fill are deleted."""
    for sub in menu.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
        sub.deleteLater()
    menu.clear()
    menu.setToolTipsVisible(True)  # the reasons on disabled items ("Diverged — use Sync")
    for item in items:
        if item.separator:
            menu.addSeparator()
            continue
        if item.children:
            sub = menu.addMenu(literal(item.label))
            fill_menu(sub, item.children, dispatch)
            sub.menuAction().setEnabled(item.enabled)
            if item.tooltip:
                sub.menuAction().setToolTip(item.tooltip)
            continue
        act = menu.addAction(literal(item.label))
        if item.checked is not None:
            act.setCheckable(True)
            act.setChecked(bool(item.checked))
        act.setEnabled(item.enabled and item.action is not None)
        if item.tooltip:
            act.setToolTip(item.tooltip)
        if item.action is not None:
            action, path = item.action, item.path
            act.triggered.connect(lambda _checked=False, a=action, p=path: dispatch(a, p))
