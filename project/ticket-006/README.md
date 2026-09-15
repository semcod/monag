# ticket-006 — Candidate-work export report

- **ID**: ticket-006
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add a `monag export` subcommand that merges three existing monag reports
into one reviewable staging list, requested as the first concrete step
toward feeding `koru`/`planfile` from monag's observations:

- `audit`'s untracked GitHub Issues (open only — a closed issue with no
  ticket is already resolved, not work) become **candidates**;
- `catalog`'s repositories with no declared description become
  **candidates** (a housekeeping signal);
- `resume`'s existing open Planfile backlog is included as **context**,
  not as candidates (they already have an id and owner).

`koru autonomous up --ticket-sources` only consumes its own `koru scan
--apply` output or the Planfile execution queue directly — there is no
generic external-JSON hook to call into. So this ticket does **not**
integrate with koru or planfile; it produces a clean, Planfile-shaped
staging list a human (or a separately authorized import step) can act on.
monag itself creates, imports, queues or claims nothing.

## Acceptance criteria

- [x] AC-01: `monag export` reports untracked (open) GitHub issues and
      undescribed repositories as `candidates`, each keeping its own
      evidence (repository, url, source), with priority passed through
      only where a source already declared one — never invented.
- [x] AC-02: Existing open Planfile tickets are included separately as
      `existing_open_tickets` (context), not mixed into `candidates`.
- [x] AC-03: A closed untracked issue and a repository with a real
      declared description are both excluded from `candidates`.
- [x] AC-04: JSON and Markdown output follow the existing `audit`/`catalog`
      conventions (`--json`, `--markdown`, `--format`); the Markdown report
      states explicitly that nothing is created or queued.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
