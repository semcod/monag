# Ticket 040: show account email in monag usage

- **ID**: ticket-040
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user requested:
"dlaczego monag usage nie pokazuje tych szcegolow konta email? ... tak"

## Goal and scope

1. Add account / email address support to `monag usage`:
   - Support explicit `"account"` or `"email"` fields in ledger documents (`api-budget-state/v1`).
   - Implement best-effort discovery (`detect_provider_account`) for local CLI provider credentials:
     - `codex` / `openai`: parse `email` from ID token in `~/.codex/auth.json`.
     - `claude` / `anthropic`: parse `emailAddress` or organization from `~/.claude.json`.
     - `agy` / `gemini` / `google`: parse `active` account from `~/.gemini/google_accounts.json`.
     - `cursor`: query cached email from Cursor state storage database.
2. Update output formats:
   - `markdown()`: add `Account` column to `## Account usage` and `## Provider accounts`.
   - `render()`: add `ACCOUNT` column to `PROVIDERS` and `ACCOUNTS` tables.
3. Add test coverage in `tests/test_usage.py` and ensure full governance conformance.

## Acceptance criteria

- [x] AC-01: `ledger_record` reads explicit `account` or `email` from ledger JSON.
- [x] AC-02: `detect_provider_account` discovers email from local credential files when not declared in ledger.
- [x] AC-03: `monag usage` markdown and plain text tables display the Account column.
- [x] AC-04: `tests/test_usage.py` passes with focused coverage for explicit and discovered accounts.
- [ ] AC-05: `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
