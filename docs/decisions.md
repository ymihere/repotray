# Decisions log

Choices made during implementation where SPEC.md / PLAN.md left room. Newest last.
Format: date — question → choice (reason).

## Decisions

- 2026-10-07 — ruff ≥ 0.15 formats Python blocks inside Markdown, which would rewrite the
  illustrative code in SPEC/PLAN → `[tool.ruff.format] exclude = ["*.md"]` (those blocks are
  documentation, not source).

## Blocked / unverified
