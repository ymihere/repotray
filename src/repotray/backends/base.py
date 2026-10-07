"""The TrayBackend protocol. Backends import their toolkit inside their own module only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from repotray.core.indicator import IconSpec
    from repotray.core.model import MenuItem, PanelModel
    from repotray.platform.base import BasePlatform


class Capabilities(TypedDict):
    tooltip: bool
    tooltip_markup: bool
    tooltip_max_chars: int | None
    label: bool
    panel: bool
    two_menus: bool
    notifications: bool
    anchor: bool


def caps(**kw) -> Capabilities:
    base: Capabilities = {
        "tooltip": False,
        "tooltip_markup": False,
        "tooltip_max_chars": None,
        "label": False,
        "panel": False,
        "two_menus": False,
        "notifications": False,
        "anchor": False,
    }
    base.update(kw)  # type: ignore[typeddict-item]
    return base


@dataclass(frozen=True, slots=True)
class ProbeResult:
    score: int  # 0 = unusable; higher wins
    reason: str


class ControllerAPI(Protocol):
    """What a backend may call on the controller (see repotray.app.Controller)."""

    def dispatch(self, action: str, path=None) -> None: ...
    def fetch_all(self) -> None: ...
    def panel_closed(self) -> None: ...
    def panel_opened(self) -> None: ...


@runtime_checkable
class TrayBackend(Protocol):
    name: ClassVar[str]
    caps: Capabilities

    @classmethod
    def probe(cls, platform: BasePlatform) -> ProbeResult: ...
    def set_icon(self, icon: IconSpec) -> None: ...
    def set_label(self, text: str) -> None: ...
    def set_tooltip(self, text: str) -> None: ...
    def set_menus(self, control: list[MenuItem], fallback: list[MenuItem] | None) -> None: ...
    def show_panel_model(self, model: PanelModel) -> None: ...
    def notify(self, title: str, body: str) -> None: ...
    def copy_to_clipboard(self, text: str) -> None: ...
    def call_soon(self, fn: Callable[[], None]) -> None: ...
    def run(self) -> None: ...
    def quit(self) -> None: ...
