# Ticket 029: Delete the head branch of a pull request closed without merging

- **ID**: ticket-029
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

## Goal and scope

Add `.github/workflows/new-project-branch-hygiene.yml`, which deletes a pull
request's head branch when that pull request is closed **without** being
merged.

`delete_branch_on_merge` is enabled on this repository, but it only covers the
merge exit. Nothing removes a branch whose pull request was closed unmerged,
and `GOV-BRANCH-LIFECYCLE-002` validates the repository as a whole rather than
the diff under review — so one left behind branch fails
`governance / remote lifecycle` on *every* later pull request, indefinitely.

Observed across the fleet on 2026-09-16: `semcod/estimation` carried two such
branches (PRs #10 and #11, both closed unmerged) and `semcod/glon` one (PR #3),
which is why unrelated pull requests in those repositories could not go green.

Closing a pull request without merging is exactly the "explicit owner decision
to discard the unmerged branch" that the check's own remediation names, and
GitHub keeps the branch restorable from the pull request page afterwards.

## Acceptance criteria

- [x] AC-01: The job runs only on `pull_request: closed` and only when the
      pull request was not merged.
- [x] AC-02: A fork head is never touched, and the default branch is never a
      deletion target.
- [x] AC-03: A branch still owned by another open pull request is kept, and
      the run says which pull request keeps it.
- [x] AC-04: An already deleted branch is a no-op, not a failure — the common
      case, because whoever closes the pull request usually ticks "delete
      branch".
- [x] AC-05: `contents: write` is granted to this job only; the workflow's
      default permission stays `contents: read`.

## Scope boundary

This is a pilot in one repository. The fleet-wide home for it is
`wellmanifest/new-project`, as `template/files/` plus a
`governance/package-manifest.json` entry, so every adopter receives it. That
change could not be allocated today: `project/new-ticket.sh` there returns
`GOV-WORK-START-001` with the `governance` workstream limit already held by
ticket-177, an unassigned branch delta on `ticket/205-coding-agent-plf-13717`,
and uncommitted work in the primary checkout. Proposed upstream instead of
being forced through.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
