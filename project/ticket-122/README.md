# Ticket 122: Reuse audit open_prs_count in monag advise to eliminate duplicate prs.scan

- **ID**: ticket-122
- **Owner**: agent:agy
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-18

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: User authorized performance optimization of `semcod/monag` and delegation to `willman`.

`monag advise` currently executes `export.scan()` (which calls `audit.scan()` and already queries open PRs across all repositories) and then calls `collect_workspace_metrics()`, which invokes `prs.scan()` a second time (54 redundant `gh` CLI calls costing ~12.5s).

Expose `open_prs_count` in `export.scan()['sources']['audit']` and reuse it in `advise.advise()` so `collect_workspace_metrics(..., include_prs=False)` skips the duplicate `prs.scan()`.

## Acceptance criteria

- [x] AC-01: `export.scan()` includes `open_prs_count` in `sources['audit']` computed from `audit_data['repositories']`.
- [x] AC-02: `advise.advise()` reuses `export_data['sources']['audit']['open_prs_count']` when `open_prs_count` is not explicitly provided and passes `include_prs=False` to `collect_workspace_metrics()` so `prs.scan()` is not called a second time.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
