# Ticket 038: action letters for open command

- **ID**: ticket-038
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked to open a listed agent by
giving its row number plus a letter choosing the action.

## Goal and scope

`monag open` (ticket-037) accepts a row number or `pid:NNNN` with
`--browser`/`--print` flags. This ticket adds the compact number+letter
form: `monag open 4t`, `monag open 4 b`, `monag open pid:2330450d`.

Action letters:

- `t` terminal (default), `b`/`w` browser route, `d` desktop UI,
  `o`/`f` open the working directory in the file manager,
  `p` print the command without spawning.
- Full action names accepted in the separate-argument form.
- Unknown letters rejected with a clear error and rc 2; a letter both
  appended and given as the second argument is an error.
- `monag shell` `open` accepts the same syntax; usage footer hint updated.

## Verification

- `tests/test_opener.py` covers parsing, action resolution and each route.
- `./project/governance-check.sh` clean.
