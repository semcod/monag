# Changelog

## [Unreleased]

### Docs
- Adopt wellmanifest/docs standard with .governance/docs.json and .governance/managed-copies.json (ticket-068)
- Conform docs/README.md and docs/information/nl-dsl-llm.md to schema and deduplication standard

## [0.3.2] - 2026-09-19

### Docs
- Update CHANGELOG.md
- Update README.md
- Update project/TICKETS.md
- Update project/ticket-067/README.md

### Other
- Update VERSION
- Update project/ticket-067/intent.json

## [0.3.2] - 2026-09-18

### Docs
- Update CHANGELOG.md
- Update project/TICKETS.md
- Update project/ticket-067/README.md

### Other
- Update VERSION
- Update project/ticket-067/intent.json


## 0.3.2 — 2026-09-18

New features and improvements since 0.3.1:

- **advise**: `monag advise` subcommand with reflex pattern integration and
  priority DSL lexicographic tiers.
- **report**: dynamic report config via email links and panel UI; hourly daemon
  and auto-detected GitHub email for digest delivery.
- **usage**: `monag usage` command for agent and account usage with balance
  column, account email, action letters, and session opening.
- **fleet**: fleet refactoring metrics in `monag resume`; conflict and duplicate
  detection delegated to `semcod/algocode`.
- **publishing**: enabled `uv build` / `uv publish` in `goal.yaml` and
  activated automated PyPI publishing via `goal -a`.

## 0.3.1 — 2026-09-16

Fixed packaging metadata. 0.3.0 declared `rich>=14,<15` and never declared
`pyyaml`, although `monag.audit` imports it, so a clean `pip install monag`
produced a command that crashed with `ModuleNotFoundError: No module named
'yaml'` on `audit`, `resume`, `export` and `panel`. Dependencies are now
`rich>=14,<16` and `pyyaml>=6,<7`, verified by running the full suite against
the installed wheel in a clean environment.

No source or behaviour change relative to 0.3.0.

## 0.3.0 — 2026-09-15

Interactive terminal agent monitoring, Markdown reports, local history, and governed publication preparation.
