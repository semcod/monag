# ticket-015 — Ignore GitHub fork repositories in the coverage audit

- **Owner**: unresolved:human (execution authorization recorded in `ai-codex.md`)
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Make the GitHub coverage audit identify repository metadata before requesting
Issues. Confirmed GitHub forks are ignored from repository totals and issue
coverage, while the JSON report retains a transparent ignored-fork inventory.
Metadata failures remain explicit and must not be interpreted as a repository
with zero Issues.

The change is limited to the audit implementation, its tests, and this ticket
carrier. It does not alter GitHub data or write to repositories being scanned.

## Acceptance criteria

- [ ] A confirmed GitHub fork is not queried with `gh issue list` and is not
      counted in repository or issue totals.
- [ ] The JSON report exposes the number and identity of ignored forks.
- [ ] A failed or malformed `gh repo view` response leaves GitHub coverage
      unknown and does not query Issues.
- [ ] Non-fork repositories and repositories without a GitHub remote retain
      their existing behavior.
- [ ] Managed governance checks and the full Python test suite pass.
- [ ] OneDev local verification, independent Validator verification, and the
      protected merge complete for the exact pushed HEAD.

## Tracking boundary

Ticket status remains `IN_PROGRESS / PUBLICATION` until the protected delivery
controller records the external merge receipt. No repository closure commit or
manual status rewrite is part of this ticket.
