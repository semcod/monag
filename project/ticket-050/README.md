# Ticket 050: audit: recent-op columns and coverage-gap diagnostics

- **ID**: ticket-050
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

## Goal and scope

Extend `monag audit --within/--last-hour` into a full picture of autonomous
system operations: the recent table now covers pull requests as well as issues
with change kind (opened/updated/closed/merged), actor, and label-derived type.
Fetching PRs also fixes a coverage defect: tickets mapped to a PR number were
misreported as orphans because `gh issue list` never returns PRs; they now land
in a separate "mapped to a pull request" section. A "Read errors — top
patterns" section groups the per-repo read failures so mass noise (e.g.
auto-mirrored `GITHUB-*` tickets missing `priority`/`inline id`) is visible
instead of a bare counter.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] Tickets mapped to an existing PR are not reported as orphans; they appear
      under `pr_tickets` with the PR state.
- [x] The recent table shows kind (issue/pr), change (opened/updated/closed/
      merged), age, actor and labels; sort is newest-first.
- [x] JSON gains `github_pr_count`, `pr_tickets`, `recent_ops`,
      `total_github_prs`, `total_pr_tickets`, `total_recent_ops`.
- [x] Read errors are grouped into a top-patterns table.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
