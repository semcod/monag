# Ticket 146: Record S4 ruleset evidence for protected standard packs

- **ID**: ticket-146
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Owner decision (2026-11-18): protect `main` with a ruleset and record S4.
Ruleset 27538025 (active, no bypass actors) blocks deletion and non-fast-forward
updates and requires `governance / enforce`, `governance / remote lifecycle`
(GitHub Actions) and `onedev/local-verify` before merge.

new-project, git-lifecycle, merge and validation-attestation move from S3 to
S4. Their S4 evidence is
`https://api.github.com/repos/semcod/monag/rulesets/27538025` with the
SHA-256 of the canonical ruleset JSON (fields id, target, enforcement,
conditions, bypass_actors, rules; sorted keys, compact separators):
`e611b1a9…43f8e`. Mode stays `audit`: worktrees, logs and docs still lack S3.

## Acceptance criteria

- [ ] AC-1: The ruleset applies to `main`.
- [ ] AC-2: The pack check reports only the three S3 gaps.
- [ ] AC-3: `project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 36/100 |
| Complexity | M |
| Estimated effort | 37 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
