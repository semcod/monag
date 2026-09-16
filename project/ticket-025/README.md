# Ticket 025: Commit the Planfile GitHub sync workflow

- **ID**: ticket-025
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

## Goal and scope

`.github/workflows/planfile-github-sync.yml` was generated on 2026-09-15 by
the Planfile tooling but never committed. It sat untracked in the primary
checkout, where it was invisible to CI and made the local governance gate
report GOV-TICKET-001 (implementation paths changed without an active
ticket). This ticket commits the file unchanged.

Effect once merged: hourly (and on any push touching `.planfile/**`) the
workflow installs `planfile==0.1.126` and runs
`planfile sync github . --repo $GITHUB_REPOSITORY --managed-only --direction both`
with `issues: write`. In this repository that reconciles the single managed
ticket `PLF-001` against GitHub issue #5. The job cannot write back to the
repository -- the reusable workflow grants `contents: read` only.

The reusable workflow was verified to exist at the pinned ref
(`semcod/planfile/.github/workflows/planfile-sync-reusable.yml@v0.1.126`).

## Acceptance criteria

- [x] AC-01: The workflow file is committed unchanged, with its pinned
      `@v0.1.126` reusable-workflow reference.
- [x] AC-02: The pinned reusable workflow exists and was read before
      committing, so the scheduled job is not a dangling reference.
- [x] AC-03: The primary checkout has no untracked implementation paths
      left, so `project/governance-check.sh` returns GOV-PASS.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
