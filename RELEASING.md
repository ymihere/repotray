# Releasing (maintainer only)

Nothing here is automated by agents: publishing is the maintainer's call.

## First publication

1. Review `git log` and `HANDOFF.md` (local, untracked); run the manual checklist in it.
2. Push: `git push -u origin main`.
3. Make the GitHub repository public (Settings → General → Danger zone → Change visibility).
4. Enable private vulnerability reporting (Settings → Code security → Private vulnerability
   reporting), which `SECURITY.md` points to.
5. Check that the CI workflow passed on GitHub (Actions tab). It has never run before the first
   push; fix any platform-specific failures (macOS/Windows jobs are the likeliest).
6. Configure PyPI trusted publishing: on pypi.org → *Your projects* → *Publishing* → add a pending
   publisher: project `repotray`, owner `ymihere`, repository `repotray`, workflow `release.yml`,
   environment `pypi`. On GitHub, create the environment `pypi` (Settings → Environments).

## Every release

1. Update `version` in `pyproject.toml` and `src/repotray/__init__.py`.
2. Move the *Unreleased* entries in `CHANGELOG.md` under the new version with today's date.
3. Local checks:
   ```sh
   ruff check . && ruff format --check .
   REPOTRAY_GUI_TESTS=1 pytest -q
   rm -rf dist && python -m build && twine check dist/*
   ```
4. Commit (`Release 0.1.0`), tag and push:
   ```sh
   git tag -a v0.1.0 -m "repotray 0.1.0"
   git push origin main v0.1.0
   ```
5. The `release` workflow builds the sdist and wheel and publishes them to PyPI. Then create a
   GitHub release from the tag with the changelog section as notes.
