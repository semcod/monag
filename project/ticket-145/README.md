# Ticket 145: Mark delivered Planfile bootstrap PLF-001 done

- **ID**: ticket-145
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

semcod/monag#5 (PLF-001, Planfile bootstrap and Wellmanifest baseline) was
delivered in PR #6 (ticket-003) and closed three times. The Planfile GitHub
sync reopens it each time because the committed store still records PLF-001
as `open`; local `planfile` writes go to the clone-operational store under
`.git/planfile-operational`.

Mark PLF-001 done with `planfile ticket done` against the committed store,
which archives it out of `.planfile/sprints/current.yaml` (as ticket-034 did
for PLF-002). The current baseline is new-project 0.20.156 (#173).

## Acceptance criteria

- [ ] AC-1: `.planfile/sprints/current.yaml` no longer carries PLF-001 as open.
- [ ] AC-2: The Planfile GitHub sync no longer reopens semcod/monag#5.
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
