# ticket-003 — Planfile bootstrap and governance reconciliation

- **Owner**: unresolved:human (accepted execution handoff recorded in `ai-codex.md`)
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Finish the already-public Planfile bootstrap on
`semcod/monag#6` / `PLF-001` so it is a canonical, independently checkable
delivery. The change keeps the Planfile store non-operational, makes the
target-owned ticket activity policy explicit, and assigns the Planfile and
activity-policy contracts to the integration workstream.

This reconciles the existing branch rather than creating a second bootstrap
ticket. It does not change application behavior, create terminal receipts, or
close tickets by editing their status projections.

## Acceptance criteria

- [x] The tracked `.planfile/` store and GitHub mapping remain present.
- [x] The repository has the strict target-owned
      `.governance/ticket-activity.override.json` using `git-ancestry` only
      for missing terminal receipts.
- [x] `.planfile/**` and the activity-policy override have an explicit
      integration-workstream owner.
- [x] `project/ticket-003/` is included in the delivery, so the implementation
      diff resolves to exactly one active ticket.
- [ ] OneDev local verification, independent Validator verification, and the
      protected merge complete for the exact pushed HEAD.

## Tracking boundary

Ticket status remains `IN_PROGRESS / PUBLICATION` until the protected delivery
controller records the external merge receipt. No repository closure commit or
manual status rewrite is part of this ticket.
