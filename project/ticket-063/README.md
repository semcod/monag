# Ticket 063: feat(advise): integrate Priority DSL tiers and readings into monag advise

- **ID**: ticket-063
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested autonomous priority preservation via Priority DSL, reflex signals, and lexicographic tiers)

## Goal and scope

1. Introduce lexicographic Priority Tiers (`floor`, `mission`, `hygiene`, `backlog`) to `monag.advise`:
   - `floor`: Governance gate failures, broken CI tests, active API friction, critical P0 blockers. Must strictly outrank all lower tiers.
   - `mission`: Active sprint tickets, release dependencies, PR reviews and merge delivery.
   - `hygiene`: Refactoring, cyclomatic complexity reduction, code smells, documentation drift.
   - `backlog`: Unscheduled ideas, improvements, feature explorations.
2. Dynamic Readings Generator:
   - Function `generate_priority_readings()` converting reflex friction patterns, governance status, and backlog stats into `wellmanifest.priority/readings/v1` envelopes.
3. Scoring & Filtering:
   - Compute tier-aware scores ensuring `floor` items always outrank lower-tier items.
   - Add `--tier` filter to `monag advise` CLI and MCP tool `monag_advise`.
4. Tests and governance:
   - 100% unit and integration tests passing.
   - `governance-check.sh` passes.

## Acceptance criteria

- [x] AC-01: `advise.classify_tier()` maps candidate origins and matched reflex risks to lexicographic tiers (`floor`, `mission`, `hygiene`, `backlog`).
- [x] AC-02: `compute_advisory_score()` enforces tier hierarchy (`floor` > `mission` > `hygiene` > `backlog`).
- [x] AC-03: `generate_priority_readings()` emits valid `wellmanifest.priority/readings/v1` data.
- [x] AC-04: `monag advise` CLI accepts `--tier [floor|mission|hygiene|backlog]`.
- [x] AC-05: MCP tool `monag_advise` accepts optional `tier` argument.
- [x] AC-06: Markdown presentation and JSON output include tier classification for every recommendation.
- [x] AC-07: Unit tests cover tier classification, readings generation, CLI filter, and MCP integration.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
