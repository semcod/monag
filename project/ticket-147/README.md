# Ticket 147: Adopt new-project 0.20.162 and record S4 ruleset evidence

- **ID**: ticket-147
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Adopt wellmanifest/new-project 0.20.162 (from 0.20.156). That release:
- inventories `.governance/docs/information/continuity-namespaces.md` as a
  managed copy, so the wellmanifest/docs checker stops rejecting it;
- stops `baseline` demanding unprovable S3 for worktrees, logs and docs;
- admits requested carrier-only follow-up commits.

The S4 evidence held back from ticket-146 (record-only changes are tracking
carriers) lands with this adoption. Ruleset 27538025 backs new-project,
git-lifecycle, merge and validation-attestation, with the SHA-256 of its
canonical JSON. With every baseline requirement proven (0 findings in strict
mode), the record moves from `audit` to `enforce` per the catalog rollout.

## Acceptance criteria

- [ ] AC-1: Goal reports the target up-to-date at 0.20.162.
- [ ] AC-2: `standard_pack_check.py --strict`: mode=enforce, 0 findings.
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
