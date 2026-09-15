# ticket-022 — Single-repository semcod/regix quality gate

- **ID**: ticket-022
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add `monag quality`: a read-only `semcod/regix` quality gate
(`regix gates --format json`) for exactly one repository.

`regix gates` runs coverage across the whole test suite plus several
static-analysis backends and costs roughly a minute per repository
(measured on monag itself: ~78s cold, ~8s once regix's own cache is warm).
Scanning a workspace of many repositories the way `catalog`/`audit`/`export`
do would take tens of minutes, so `monag quality` refuses workspace mode
outright (`--root` must be a Git checkout) instead of silently taking that
long. This is a deliberately different cost/scope model from the earlier
Tier-2/3 integrations (`--radar`, `--hygiene` on `export`), which is why it
is its own subcommand rather than a flag on an existing one.

## Acceptance criteria

- [x] AC-01: `monag quality` reports `ref`, `all_passed`,
      `error_count`/`warning_count`, and the full `violations` list from
      `regix gates --format json`.
- [x] AC-02: `--root` pointing at a workspace (not itself a Git checkout)
      is refused with an explicit reason, never silently attempted.
- [x] AC-03: A missing `regix` binary, a `run_regix` failure, or invalid
      output are all explicit `available: false` results with a reason,
      never a crash or a silent "clean" result.
- [x] AC-04: Only `regix gates` is ever invoked — no write/fix command.
- [x] AC-05: Exit code is `2` when unavailable, `1` when gates fail, `0`
      when they pass, for scripting.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
