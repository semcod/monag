# Ticket 046: opencode session resume and account probe

- **ID**: ticket-046
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: continue the numbered improvement list —
extend per-session resume to opencode and probe its account.

## Goal and scope

- `opencode`: the CLI supports `-s/--session <id>`; its
  `~/.local/share/opencode/opencode.db` `session` table records
  `directory` and `time_updated`. Resolve the running session as the
  newest row whose `directory` equals the process cwd and open
  `opencode --session <id>`. Read-only sqlite connection; any failure
  falls back to the existing bare `opencode` recipe.
- `detect_provider_account('opencode')`: read the `account_state`/
  `account` join (or `control_account` where active) for a logged-in
  email. When the tables are empty the honest `—` remains.
- `devin` exposes only `org_id` (no email) — stays `—`.

## Verification

- `tests/test_opener.py` builds a fake opencode.db and asserts
  `--session` resolution plus the no-match fallback.
- `tests/test_usage.py` covers the opencode account probe.
- `./project/governance-check.sh` clean.
