# Porting repotray

repotray's core knows nothing about desktops. A port means implementing a **tray backend** (how the
icon, menus and panel are shown) and/or a **platform** (OS services), then running the conformance
suite and filing a platform report. You never need to touch `repotray/core/`.

The most wanted ports: a panel on macOS — try the `qt` backend there first (`pip install
"repotray[qt]"`, `--backend qt`; written for Windows, untested on macOS), else `NSPopover` via
PyObjC — and status-item titles (counts next to the icon) on macOS. Windows has the full panel
through the `qt` backend.

## Try it without your repositories

- `repotray tray --demo` shows eleven fabricated repositories and simulates actions (1.5 s each;
  pulling `mobile-app` fails on purpose).
- `repotray tray --backend fake` runs the whole app with a backend that only records calls.
- `repotray doctor` shows every backend, its probe score and the reason.

## The TrayBackend protocol

`repotray/backends/base.py`:

```python
class Capabilities(TypedDict):
    tooltip: bool; tooltip_markup: bool; tooltip_max_chars: int | None
    label: bool; panel: bool; two_menus: bool; notifications: bool; anchor: bool

class TrayBackend(Protocol):
    name: ClassVar[str]
    caps: Capabilities
    @classmethod
    def probe(cls, platform) -> ProbeResult: ...          # ProbeResult(score, reason); 0 = unusable
    def __init__(self, platform, controller) -> None: ...
    def set_icon(self, icon: IconSpec) -> None: ...
    def set_label(self, text: str) -> None: ...
    def set_tooltip(self, text: str) -> None: ...
    def set_menus(self, control: list[MenuItem], fallback: list[MenuItem] | None) -> None: ...
    def show_panel_model(self, model: PanelModel) -> None: ...   # no-op unless caps["panel"]
    def notify(self, title: str, body: str) -> None: ...
    def copy_to_clipboard(self, text: str) -> None: ...
    def call_soon(self, fn: Callable[[], None]) -> None: ...     # thread-safe; run fn on the UI thread
    def run(self) -> None: ...                                    # blocks until quit()
    def quit(self) -> None: ...
```

### Capabilities contract

| Capability | If `True`, the backend… | If `False`, the controller… |
|---|---|---|
| `tooltip` | shows `set_tooltip` text on hover | never calls `set_tooltip` |
| `tooltip_markup` | accepts Pango markup (`<b>`, escaped names) | sends plain text |
| `tooltip_max_chars` | — | (when set) sends a one-line summary within the limit |
| `label` | shows text next to the icon | puts counts in the tooltip and menu only |
| `panel` | hosts a popup window built from `PanelModel` | renders the panel as a menu (`fallback`) |
| `two_menus` | has a separate right-click menu | — |
| `notifications` | implements `notify` itself | uses `platform.notify` |
| `anchor` | knows the icon rectangle for placing the panel | — (panel opens at the pointer) |

Optional extras a backend may provide: `install_signal_handlers(on_quit)`, `show_about(info)`,
`open_panel()`, `ui_thread` (the thread `call_soon` runs on, if not the one calling `run`),
`wants_fallback_menu = True` and `has_panel = True` (for hosts like AppIndicator whose left click
always opens a menu: the menu then starts with *Open panel…*).

### What the controller gives you

- `IconSpec(state, top, bottom, tint, glyph_color)`: `state` is `clean`, `attention`, `error` or
  `paused`; colours are `foreground`, `warning`, `error`, `success` or `#rrggbb`.
  `repotray.icons.names.icon_name(spec)` gives the symbolic theme icon name,
  `repotray.icons.svg.write_hex_icon(spec, dir)` a full-colour SVG file,
  `repotray.icons.raster.render(spec, size, glyph_color)` a Pillow image.
- `MenuItem(label, action, enabled, checked, children, separator, path, tooltip)`. When the user
  activates an item, call `controller.dispatch(item.action, item.path)` — on the UI thread.
- `PanelModel`: everything the panel shows, as plain data (see `repotray/core/model.py`). The GTK
  implementation in `repotray/ui/gtk3/panel.py` is the reference layout; `repotray/ui/qt/panel.py`
  is the same layout in Qt 6 (the `qt` backend), a second example of a complete port.

### Threading

`set_*`, `show_panel_model` and `notify` are called on the UI thread. `call_soon` is called from any
thread. Never block the UI thread; the controller never runs git on it.

## A complete minimal backend package

```
repotray-hello/
├── pyproject.toml
└── repotray_hello.py
```

`pyproject.toml`:

```toml
[project]
name = "repotray-hello"
version = "0.1.0"
dependencies = ["repotray"]

[project.entry-points."repotray.backends"]
hello = "repotray_hello:HelloBackend"
```

`repotray_hello.py` — a backend that prints state changes to the terminal:

```python
import queue
import threading

from repotray.backends.base import ProbeResult, caps


class HelloBackend:
    name = "hello"
    caps = caps(tooltip=True, label=True)

    @classmethod
    def probe(cls, platform):
        return ProbeResult(1, "prints to the terminal")  # low: only used when asked for

    def __init__(self, platform, controller):
        self.controller = controller
        self.q = queue.Queue()

    def set_icon(self, icon):
        print("icon:", icon.state, icon.top, icon.bottom, icon.tint)

    def set_label(self, text):
        print("label:", text)

    def set_tooltip(self, text):
        print("tooltip:\n" + text)

    def set_menus(self, control, fallback):
        print("menu:", [i.label for i in (fallback or control) if not i.separator])

    def show_panel_model(self, model):
        pass

    def notify(self, title, body):
        print("notify:", title, body)

    def copy_to_clipboard(self, text):
        print("copy:", text)

    def call_soon(self, fn):
        self.q.put(fn)

    def run(self):
        threading.Timer(30, self.quit).start()  # demo: stop after 30 s
        while (fn := self.q.get()) is not None:
            fn()

    def quit(self):
        self.q.put(None)
```

Install it next to repotray (`pip install -e repotray-hello`) and run
`repotray tray --demo --backend hello`. `repotray doctor` lists it with its probe score. Built-in
names cannot be overridden by plugins.

## The Platform protocol

`repotray/platform/base.py` defines `Platform`; `BasePlatform` supplies defaults. Implement:
`config_dir`, `state_dir`, `cache_dir`, `runtime_dir`, `git_env`, `popen_kwargs`, `kill_tree`,
`acquire_instance_lock` (returns `None` when already held; writes the pid), `read_lock_pid`,
`open_terminal(path, template)`, `open_folder(path, template)`, `open_file(path)`,
`notify(title, body) -> bool`, `autostart_enable(argv) -> str`, `autostart_disable`,
`autostart_enabled`, `install_icons(src)`, `uninstall_icons`, `icons_installed`, `desktop_info`,
`prefers_dark_panel`. Register a new OS in `repotray/platform/__init__.py:for_name()`; see
`tests/unit/test_platform_other.py` for how macOS and Windows are tested with mocks.

## Conformance suite

```sh
REPOTRAY_BACKEND=hello pytest tests/conformance                      # headless backends
REPOTRAY_BACKEND=xapp REPOTRAY_GUI_TESTS=1 pytest tests/conformance   # backends needing a display
```

It checks that every `IconSpec`, labels, tooltips (within `tooltip_max_chars`), nested menus and the
panel model are accepted, that `call_soon` from another thread runs on the UI thread, and that
`quit()` makes `run()` return promptly. Then try it for real with `repotray tray --demo`.

## Platform report

Open a *Platform report* issue with: OS and version, desktop and session type (X11/Wayland),
backend, `repotray doctor` output, conformance results, and screenshots (from `--demo` only) of the
icon in each state, the tooltip, the menu and the panel if any. Say what did not work — that is the
useful part.
