# ticket-028 — Revert the Planfile GitHub issue mirror

- **ID**: ticket-028
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

## Goal and scope

Revert `.planfile/` to its state before ticket-027 (commit `565f4aa`).

ticket-027 committed the output of a local `planfile sync github` run: 26
`GITHUB-*` tickets mirroring this repository's issues **and pull requests**,
plus their mapping in `.planfile/sync/github.state.yaml`. Its commit message
asserted that the hourly reconciliation job from ticket-025 would not push
those entries back, because they carry no `managed` label. That assertion was
wrong, and it broke two things in production:

1. **A closed issue was reopened.** The mirror recorded `GITHUB-25` as `open`;
   issue #25 had been closed after the sync ran. The push-triggered
   reconciliation at 11:47 pushed the stale status, and `github-actions[bot]`
   reopened #25 at 11:48:09.

2. **Every sync run now fails.** `GITHUB-1` maps to `semcod/monag#1`, which is
   a *pull request*, not an issue. Reconciliation tries to create or update it
   as an issue and dies:
   `GitHub permission denied for GITHUB-1 / Your GitHub token lacks permission
   to create issues`. Both the 11:47 push run and the 12:37 scheduled run
   failed this way.

`--managed-only` does not filter on the `managed` label as assumed; the
reconciliation acts on every ticket carrying a `sync.github` mapping.

With `.planfile/` restored, the tracked store holds only `PLF-001`, whose
mapping to issue #5 is consistent, so the hourly job has exactly one
well-formed ticket to reconcile.

## Acceptance criteria

- [x] AC-01: `.planfile/sprints/backlog.yaml` is empty of `GITHUB-*` tickets
      and `.planfile/sync/github.state.yaml` maps only `PLF-001`.
- [ ] AC-02: The next `planfile-github-sync` run succeeds.
- [ ] AC-03: Issue #25 is closed again and stays closed across a sync run.

## Consequence accepted

A local `planfile sync github` run rewrites these files again, and an
uncommitted `.planfile/` delta blocks ticket allocation and turns the local
gate red. That is the pre-existing condition; committing the mirror was the
wrong way to resolve it. The right resolution is either to stop running the
sync locally or to ignore the generated sprint files, and it belongs in its
own ticket.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
