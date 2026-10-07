"""The incoming-commits dialog and the Details dialog of an action result."""

from __future__ import annotations

import html
import time
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from repotray.core.model import ACTION_ICONS, ago
from repotray.ui.qt.icons import set_icon
from repotray.ui.qt.menus import literal
from repotray.ui.qt.widgets import bold, dim
from repotray.ui.text import (
    ACTION_LABELS,
    NO_INCOMING_TEXT,
    blocked_text,
    commit_epoch,
    details_text,
    more_commits_text,
)


def _window_flags(dialog: QDialog) -> None:
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)


def commits_html(log, now: float) -> str:
    """The commit list as HTML for a QTextBrowser; colours come from the palette."""
    if not log.commits:
        return f"<p>{html.escape(NO_INCOMING_TEXT)}</p>"
    mono = html.escape(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
    parts = []
    for c in log.commits:
        when = ago(commit_epoch(c.date), now)
        meta = (
            f"<span style=\"font-family:'{mono}'\">{html.escape(c.sha[:8])}</span>"
            f" · {html.escape(c.author)} · {html.escape(when)}"
        )
        parts.append(f"<p style='margin-bottom:0'><b>{html.escape(c.subject)}</b></p>")
        parts.append(f"<p style='margin-top:2px'><i><small>{meta}</small></i></p>")
        if c.body:
            body = html.escape(c.body).replace("\n", "<br>")
            parts.append(f"<p style='margin-left:24px'>{body}</p>")
    if log.total > len(log.commits):
        more = html.escape(more_commits_text(log.total - len(log.commits)))
        parts.append(f"<p><i><small>{more}</small></i></p>")
    return "\n".join(parts)


class CommitsDialog(QDialog):
    """The commits a pull would bring, with *Open in editor* and a Pull (or Sync) button."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        subtitle: str,
        log,
        on_open_editor: Callable[[], None],
        action=None,
        on_action: Callable[[], None] | None = None,
    ) -> None:
        """``action`` is the model's Button for Pull (or Sync); None = no such button."""
        super().__init__(parent)
        _window_flags(self)
        self.setWindowTitle(f"repotray — {title}")
        self.resize(640, 460)
        self.on_open_editor = on_open_editor
        self.on_action = on_action

        lay = QVBoxLayout(self)
        heading = bold(QLabel(title))
        heading.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(heading)
        sub = dim(QLabel(subtitle))
        sub.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(sub)
        self.reason: QLabel | None = None

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setHtml(commits_html(log, time.time()))
        lay.addWidget(self.view, 1)

        self.buttons = QDialogButtonBox()
        self.editor_button = self.buttons.addButton(
            "Open in editor", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.editor_button.clicked.connect(self.on_open_editor)
        close = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.close)
        self.action_button: QPushButton | None = None
        if action is not None and on_action is not None:
            label = ACTION_LABELS[action.action.value]
            b = self.buttons.addButton(literal(label), QDialogButtonBox.ButtonRole.AcceptRole)
            set_icon(b, ACTION_ICONS[action.action], literal(label))
            b.setEnabled(action.enabled)
            b.setToolTip(action.tooltip)
            b.clicked.connect(self._act)
            self.action_button = b
            if action.enabled:
                b.setDefault(True)
            else:
                self.reason = dim(QLabel(blocked_text(label, action.tooltip)))
                self.reason.setTextFormat(Qt.TextFormat.PlainText)
                self.reason.setWordWrap(True)
                lay.insertWidget(2, self.reason)
        if self.action_button is None or not self.action_button.isEnabled():
            close.setDefault(True)
        lay.addWidget(self.buttons)

    def _act(self) -> None:
        if self.on_action is not None:
            self.on_action()  # the panel shows progress and the result
        self.close()


class DetailsDialog(QDialog):
    """The exact commands, exit status and full output of an action."""

    def __init__(self, parent: QWidget | None, result) -> None:
        super().__init__(parent)
        _window_flags(self)
        self.setWindowTitle(f"repotray — {result.name}")
        self.resize(640, 360)
        self.text = details_text(result)
        lay = QVBoxLayout(self)
        view = QPlainTextEdit(self.text)
        view.setReadOnly(True)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(view, 1)
        buttons = QDialogButtonBox()
        copy = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.close)
        close.setDefault(True)
        lay.addWidget(buttons)
