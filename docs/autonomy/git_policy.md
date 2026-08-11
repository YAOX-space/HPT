# Git Policy

- Begin each session with `git status --short --branch`.
- Work on a named research branch for long-running autonomous work.
- Never revert user changes unless explicitly instructed.
- Commit only task-owned files with explicit pathspecs.
- Keep commits narrow and reversible.
- Tag only validated reproducible baselines.
- Force-add `.codex/skills/hpt-research-agent` when committing the project
  skill because `.codex/` is ignored by default.
- Do not commit generated caches, `slprj/`, `*.slxc`, large datasets, or raw
  result payloads unless the user explicitly asks.
