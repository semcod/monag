# Ticket 152: Add optional urtlog dependency extra in pyproject.toml

- **ID**: ticket-152
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20
- **Authorization**: `SESSION_EXECUTION_AUTHORIZATION` (user autonomous pilot rollout mandate for `uritime/urtlog` packaging extras across Python projects, including publication through the repository's protected delivery process)

## Goal and scope

Declare `urtlog = ["uritime-urtlog>=0.3.0"]` under `[project.optional-dependencies]` in `pyproject.toml` so operators can install `monag[urtlog]` from a local wheelhouse or registry without changing mandatory runtime dependencies or offline CI.

## Acceptance criteria

- [x] AC-01: `pyproject.toml` declares `urtlog = ["uritime-urtlog>=0.3.0"]` under `[project.optional-dependencies]` while leaving `[project].dependencies` unchanged.
- [x] AC-02: `pytest` and `./project/governance-check.sh` pass with 0 errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 40/100 |
| Complexity | M |
| Estimated effort | 45 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
