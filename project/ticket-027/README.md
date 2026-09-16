# Ticket 027: Commit the Planfile GitHub issue mirror

- **ID**: ticket-027
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

## Goal and scope

A local `planfile sync github` run on 2026-09-16 09:14 local time wrote the
repository's Planfile store: it imported every GitHub issue and pull request
of `semcod/monag` into `.planfile/sprints/backlog.yaml` as `GITHUB-*`
tickets, extended `.planfile/sync/github.state.yaml` with their mapping, and
round-tripped `PLF-001` through issue #5 (deduplication-key marker, the
`planfile`/`managed`/`priority-high` labels, `metadata.deduplication_key`).

The result sat uncommitted in the primary checkout, which blocked ticket
allocation and made `project/governance-check.sh` report GOV-TICKET-001.
This ticket commits the store as the tool wrote it -- no hand edits; the
store is event-sourced with hashed DSL records.

## Two properties of the committed snapshot

- **It mirrors pull requests as tickets.** `GITHUB-17`, `GITHUB-24` and
  `GITHUB-26` are PRs, not issues. They carry no labels, so they are not
  `managed`.
- **It is a point-in-time snapshot and is already stale in one place.**
  `GITHUB-25` is recorded `open`; issue #25 was closed after the sync ran.
  That entry is not `managed` either.

The five `managed` entries (`GITHUB-2`, `-3`, `-4`, `-7`, `-16`) and
`PLF-001` all match GitHub's current state, so the hourly reconciliation
job committed in ticket-025 has nothing to flip back.

## Acceptance criteria

- [x] AC-01: The store is committed exactly as the tool wrote it.
- [x] AC-02: The primary checkout has no pending delta left, so
      `project/governance-check.sh` returns GOV-PASS.
- [x] AC-03: The test suite still passes (the store is data, not code).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
