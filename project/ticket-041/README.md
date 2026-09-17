# Ticket 041: open hint in default usage view

- **ID**: ticket-041
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user reported the default `monag
usage` view lacks the open-a-row hint.

## Goal and scope

The default terminal view renders `usage.markdown()` through Rich; the
`monag open N[t|b|d|o|p]` hint added in tickets 037/038 only appears in
the `--plain` renderer. Append the same hint line to the markdown output
when agents are listed so every display mode advertises row opening.

## Verification

- `tests/test_usage.py` asserts the hint in markdown output.
- `./project/governance-check.sh` clean.
