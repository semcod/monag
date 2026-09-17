# Ticket 042: add balance column in monag usage

- **ID**: ticket-042
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user requested:
"tam gdzie sa API dodaj kolumne Balance z informacja o stanie w monag"

## Goal and scope

1. In `src/monag/usage.py`:
   - Support `balance` and `balance_text` fields in `ledger_record()` from `subactor.api-budget-state/v1` documents.
   - Add `Balance` column to `## Account usage` and `## Provider accounts` in `markdown()`.
   - Add `BALANCE` column to `PROVIDERS` and `ACCOUNTS` tables in `render()`.
2. In `tests/test_usage.py`:
   - Add test coverage verifying `balance` column presence in markdown and render text.
   - Add `test_ledger_explicit_balance`.

## Acceptance criteria

- [x] AC-01: `ledger_record()` extracts `balance` or `balance_text` from ledger documents.
- [x] AC-02: `markdown()` includes `Balance` column in account and provider tables.
- [x] AC-03: `render()` includes `BALANCE` column in `PROVIDERS` and `ACCOUNTS` tables.
- [x] AC-04: `tests/test_usage.py` passes with test coverage for `balance`.
- [ ] AC-05: `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
