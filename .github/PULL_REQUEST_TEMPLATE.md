## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] `pytest -q` passes (and `REPOTRAY_GUI_TESTS=1 pytest -q` for UI changes)
- [ ] `ruff check . && ruff format --check .` pass
- [ ] UI changes were looked at (`--demo`, `scripts/dev/render-panel.py`); screenshots attached
- [ ] Docs updated (`docs/configuration.md`, `docs/cli.md`, README) where behaviour changed
- [ ] `CHANGELOG.md` entry under *Unreleased*
- [ ] Nothing under `repotray/core/` or `repotray/platform/` imports a GUI toolkit
