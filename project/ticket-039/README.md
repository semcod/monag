# Ticket 039: provider accounts table in monag usage

- **ID**: ticket-039
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user requested:
"dodaj do monag usage dodatkowa tabele ponizej w ktorej beda tylko konta providerow za informacja ile zostalo i kiedy odnowienie"

## Goal and scope

1. Add automatic discovery of default local ledger sources (`~/.config/subllm/ledgers`, `~/.subllm/ledgers`) when `--ledger` is not explicitly passed, so provider accounts are naturally visible in `monag usage`.
2. Format a dedicated provider accounts table in `monag usage` output (`markdown` and `render` plain text) with columns focused on:
   - `Provider`
   - `Remaining` (ile zostało)
   - `Renewal` (kiedy odnowienie)
   - `Status` (zwięzły status)
3. Ensure backwards compatibility with existing tests and ledger options.

## Acceptance criteria

- [ ] AC-01: `monag usage` automatically scans default ledger paths when available.
- [ ] AC-02: `monag usage` formats the dedicated provider accounts table showing remaining quota and renewal time.
- [ ] AC-03: `tests/test_usage.py` passes with focused test coverage for the provider table and default discovery.
- [ ] AC-04: `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
