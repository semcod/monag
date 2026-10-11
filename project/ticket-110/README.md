# Ticket 110: Usage: mark stale budget observations unknown before scheduling

- **ID**: ticket-110
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-11

## Goal and scope

Add a tested freshness contract in `src/monag/usage.py` for absent, malformed, stale, future `observed_at` and expired reset windows (`reset_at`). Preserve historical remaining values separately while marking current balance/remaining as unknown/stale (`freshness` state). Prevent stale balance observations from being treated as valid or exhausted balances during dispatch/account rotation, and communicate unknown balance in rendered views and JSON output.

## Acceptance criteria

- [x] AC-01: Implement freshness validation contract in `src/monag/usage.py` for ledger records.
- [x] AC-02: Mark ledger status as `unknown` / `stale` when `observed_at` is absent, malformed, expired (> freshness threshold, e.g. 24h default or passed reset_at), or in the future.
- [x] AC-03: Preserve historical remaining in `historical_remaining` or `last_observed_remaining`, while reflecting freshness state and rendering unknown balance appropriately.
- [x] AC-04: Add comprehensive tests in `tests/test_usage.py` covering all freshness edge cases (absent, malformed, stale, future, expired reset).
- [x] AC-05: Ensure unit tests pass and `./project/governance-check.sh` passes with zero errors and zero warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
