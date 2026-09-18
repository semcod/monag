# Ticket 044: interactive cursor picker for open command

- **ID**: ticket-044
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: continuing the user's request to select a
listed agent "poprzez kursor" — a bare `monag open` should offer cursor-key
selection instead of requiring a row number.

## Goal and scope

- `monag open` with no target opens an interactive picker when stdin is a
  tty: ↑/↓ or j/k move the cursor, `t`/`b`/`d`/`o`/`f`/`p` pick the action
  directly, Enter opens the default (terminal) action, `q`/Esc/Ctrl-C
  cancels. Rows show the same `#`, PID, kind, account and directory as the
  usage table, limited by `--limit`.
- `monag open --browser` uses the picker with browser as the Enter action;
  `--print` previews the command.
- Non-tty without a target keeps a clear error and rc 2.
- `monag shell` bare `open` uses the same picker.
- Read-only: scanning stays passive; only the chosen action spawns.

## Verification

- `tests/test_opener.py` drives `choose()` with scripted key streams:
  movement, wrap-around, letters, Enter, quit, empty list, tty guard.
- `./project/governance-check.sh` clean.
