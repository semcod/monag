# Ticket 030: Report fleet refactoring metrics

- **ID**: ticket-030
- **Owner**: claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked for monag to report the
statistics collected by hand during a fleet audit, because those metrics are
needed to plan a refactoring of the project fleet, and asked for a Planfile
ticket so the work is tracked and delegable to Koru.

## Goal and scope

A manual audit on 2026-09-17 counted unfinished work across 1534 fleet
checkouts and reported 142 unpublished branches. The real number was 8. Every
error inflated the same direction, and each came from a distinct trap:

1. **Stale base ref** — `ahead > 0` measured against an `origin/main` that was
   never fetched reports delivered work as pending. 142 → 125 after fetching.
2. **Parallel clones** — the fleet holds several clones of one repository
   (`subactor/docs` and `subactor-lifecycle-v7/docs`), so per-checkout sums
   count one branch many times. 125 → 38 after keying by repository identity.
3. **Squash and rebase merges** — a squashed branch never becomes an ancestor
   of the base, so ancestry alone reports it unpublished forever. 38 → 8 after
   checking each branch against its pull request.

`inspect_checkout` already computes `ahead`/`behind` and reads `lease_status`,
and reports `ahead > 0` as `unmerged commits`, which carries all three traps.
Publish the metrics with the distinctions that make them safe to aggregate, so
a refactoring plan is not built on an 18x overcount.

Scope is local and read-only: no fetch, no network, no ref mutation, no lease
takeover. Ancestry therefore yields `unmerged_by_ancestry`, named as a
*candidate* state, and the accompanying note says a pull-request lookup is
required to settle it.

## Acceptance criteria

- [x] AC-01: The user's explicit request approves the bounded scope.
- [x] AC-02: `publication_state` separates `dirty`, `unmerged_by_ancestry`,
      `merged_by_ancestry`, `no_remote` and `no_base`; dirty outranks ancestry
      and a missing base is never reported as unmerged.
- [x] AC-03: Aggregates deduplicate by `(remote_identity, branch)` and report
      the duplicate count instead of hiding it; the existing suite still passes.
- [x] AC-04: Metrics are produced against the live fleet, including the age of
      the comparison base and the count of lease claims older than the
      staleness threshold.
- [ ] AC-05: Governance validation passes.

## Delegation

Three prerequisites block Koru delegation, none of them resolved here:

1. `.planfile/**` belongs to the **integration** workstream, so a Planfile
   ticket cannot ride in this `application` ticket; it needs its own.
2. `semcod/monag` has neither `.koru/policy.yaml` nor `koru.yaml`, so the Koru
   fleet does not cover this repository and its queue cannot see the work.
3. `planfile sync github` cannot publish a new ticket. Import was reverted in
   PR #29 for mirroring pull requests as issues; export is defective too — on
   2026-09-17 `--direction to` reported `Created: PLF-003 -> 19` while creating
   no issue and recording a mapping onto pull request #19.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
