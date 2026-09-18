# Ticket 051: Add monag prs command for Pull Requests and branch audit

- **ID**: ticket-051
- **Owner**: tom
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested unmerged PR and branch audit command in chat)

## Goal and scope

Add `monag prs` (with alias `monag pr`) command and interactive shell action to audit Pull Requests (open, merged, closed) and correlate them with local branches across workspace repositories. Also enhance `monag audit` with PR open/merged breakdown.

## Acceptance criteria

- [x] AC-01: `monag prs` command scans repositories for PR activity within a time window (default: 24h) and detects unpushed commits / branches without PR.
- [x] AC-02: `monag prs` correlates local branches with open and merged GitHub Pull Requests via `gh`.
- [x] AC-03: `monag audit` includes PR status breakdown (open vs merged).
- [x] AC-04: `prs` command is integrated into `monag shell`.
- [x] AC-05: Markdown and JSON output formats (`--json`, `--plain`, `--markdown`) are supported.
- [x] AC-06: Unit tests verify PR scanning, branch matching, and report rendering.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

