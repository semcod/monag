# ticket-014 — Planfile backlog visibility and interactive shell

- **ID**: ticket-014
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Show local Planfile work at startup and provide a small interactive shell for
read-only workspace reports. Preserve script-friendly one-shot commands and the
explicit continuously refreshing `watch` mode.

## Acceptance criteria

- [ ] AC-01: The shell displays the dashboard and Planfile resume report before
      accepting commands.
- [ ] AC-02: `help`, `refresh`, `status`, `resume`, `audit`, `catalog`,
      `history`, `quit`, and `exit` work without taking ownership of work.
- [ ] AC-03: A repository-local Planfile and GitHub sync workflow are tracked.

## Tracking boundary

This directory contains the reviewed intent; no human-owned input files are
created by automation.
