# Ticket 043: account email column in agents table

- **ID**: ticket-043
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user reported that the first `monag
usage` table does not show which account/email each agent belongs to and
asked for an account-email column.

## Goal and scope

Add an `Account` column to the Agents table (both the Rich markdown view
and `--plain` render). Each agent row resolves its provider through a
`kind`→provider map (`agy` family → `agy`, `claude*` → `claude`,
`codex`, `cursor-agent` → `cursor`, `gemini`) and shows the logged-in
account email discovered by the existing `detect_provider_account()`
credential-file probe; when detection finds nothing, the observed ledger
account for the same provider is the fallback. Unknown providers show
`—`. Detection runs once per provider, not per row.

## Verification

- `tests/test_usage.py` covers credential-file detection and the ledger
  fallback on fake `/proc` + fake home fixtures.
- `./project/governance-check.sh` clean.
