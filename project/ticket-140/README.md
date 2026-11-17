# Ticket 140: Honor the requested hours window in the day report

- **ID**: ticket-140
- **Owner**: agent:claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-17

## Authorization

`SESSION_EXECUTION_AUTHORIZATION` recorded from the operator's session request
of 2026-11-17 ("zbadaj semcod/monag, diagit i subactor/reflex z ostatnich 12
godzin i wyciągnij wnioski i naprawiaj błędy").

## Allocation note

The repository's allocator scaffolded `project/ticket-140` in the primary
checkout without a linked worktree. The directory was moved unchanged into the
canonical Worktrees v5 location planned by
`.governance/worktree_path_check.py plan` (`.worktrees/ticket-140--day-hours-window`,
branch `ticket/140-day-hours-window`, based on `origin/main`); the primary
checkout was left as found.

## Goal and scope

`monag --hours 12 day` printed "24h Operational Delta … okno: 12.0h",
"Ukończone zadania (okno 24h)" and queried GitHub with `merged:>=<today>` /
`created:>=<today>`, so the PR delta covered the calendar day (72 merged)
rather than the requested 12 hours (47 merged). Only blockers and agent runs
honoured `--hours`.

In `src/monag/summary.py`:

1. `day` without a pinned `target_date` queries GitHub with a rolling UTC
   window `>=YYYY-MM-DDTHH:MM:SSZ` (now − hours); `summary` and a pinned date
   keep the calendar-day query.
2. Labels, headings and filters show the real window; Planfile completions,
   which are recorded per calendar day, are labelled
   "dzień kalendarzowy <date>" instead of "okno 24h".
3. JSON gains `github_window_since`. Integral float hours render as `12h`.

## Acceptance criteria

- [x] AC-01: `day --hours 12` passes `since = now − 12h` to the PR query and
  shows the same timestamp in labels and Markdown; no "24h" text remains.
- [x] AC-02: `summary` and a pinned `target_date` keep calendar-day semantics.
- [x] AC-03: `gh search prs` receives `--merged-at >=<ISO>` and `--created >=<ISO>`.
- [x] AC-04: Ruff on changed files, the full pytest suite and
  `./project/governance-check.sh` pass. `tests/test_procache_integration.py`
  fails identically on untouched `origin/main` in this environment and is
  outside this ticket.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
