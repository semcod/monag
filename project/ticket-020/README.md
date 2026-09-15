# ticket-020 — Size export candidates with subactor/ticket-radar

- **ID**: ticket-020
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add `monag export --radar`: when `subactor/ticket-radar` is installed on
PATH, size each candidate (complexity, score, time estimate, split
recommendation) via its deterministic JSON stdin/stdout interface —
`ticket-radar --repository-root <path> -`. This is the first concrete
Tier-2 integration from the earlier package survey (`subactor/*`): a
metric-based signal for autonomous prioritization instead of a guess.

A missing binary or a per-candidate failure leaves that candidate unsized
(`radar: null`) with an explicit error recorded in `radar_errors`, never a
guessed size. Off by default — `monag export` without `--radar` behaves
exactly as before.

## Acceptance criteria

- [x] AC-01: `--radar` sizes each candidate with `complexity`, `score`,
      `estimated_minutes`, `within_budget`, `diagnostics`, and
      `split_recommended`, read from ticket-radar's own JSON output.
- [x] AC-02: A missing `ticket-radar` binary leaves every candidate without
      a `radar` key and records one explicit error, not a crash or a guess.
- [x] AC-03: A per-candidate ticket-radar failure (timeout, bad output)
      leaves `radar: null` on that candidate with its own recorded error.
- [x] AC-04: Markdown output adds a Radar column only when `--radar` was
      requested; unsized candidates show `unsized`, never a blank guess.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
