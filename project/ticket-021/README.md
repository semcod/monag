# ticket-021 — Add taskill doc-hygiene candidates to export

- **ID**: ticket-021
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add `monag export --hygiene`: a `taskill-doc-drift` candidate for every
repository where `semcod/taskill`'s own read-only `status` command (never
`run` — monag never asks an external tool to write) reports it would
update README/CHANGELOG/TODO, carrying taskill's own reasons (pending
commits, changed docs) as evidence. Second concrete Tier-2/3 integration
from the package survey, alongside `--radar` (ticket-020).

A missing binary or a per-repository failure is an explicit recorded
error, never silently treated as "nothing to do".

## Acceptance criteria

- [x] AC-01: `--hygiene` adds a candidate for every repository where
      `taskill status --format json` reports `would_run: true`, with its
      `reasons` as evidence.
- [x] AC-02: A repository taskill reports clean (`would_run: false`)
      produces no candidate.
- [x] AC-03: A missing `taskill` binary records one explicit error and adds
      no candidates, never silently assuming everything is clean.
- [x] AC-04: monag only ever invokes `taskill status`, never `taskill run`
      or any other write-capable subcommand.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
