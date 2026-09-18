# Ticket 049: audit: time-window filter and recent-issues table

- **ID**: ticket-049
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

## Goal and scope

`monag audit` gains a time-window view of GitHub issue activity. `--within
HOURS` (alias `--last-hour` for 1 h) filters each repository's fetched issues
by `updatedAt` and renders an extra "GitHub issues updated in the last N h"
table (repository, issue, state, age, title). Without the option the report is
unchanged. Read-only: no writes to Planfile or GitHub; the same already-fetched
issue payload is reused, so the option adds no extra `gh` calls.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] `monag audit --within 1` lists only issues whose `updatedAt` lies inside
      the window; `--last-hour` is equivalent.
- [x] Issues with missing or malformed `updatedAt` are excluded, never guessed.
- [x] JSON output carries `recent_hours`, per-repo `recent_issues` and
      `total_recent_issues` (`null` when the option is off).
- [x] Interactive shell `audit` honours the same options.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
