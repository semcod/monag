# Ticket 090: Fix subllm route invocation in autodiagnosis and add daily summary command

- **ID**: ticket-090
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-25

## Goal and scope

1. Fix `_find_subllm_runner` in `autodiagnosis.py` to invoke SubLLM with valid application (`koru-agent`) and function (`nl-to-koru-dsl`) routes instead of calling `complete(messages)` without required route arguments.
2. Add a native `monag summary` (and `monag day`) command that aggregates:
   - Planfile completed tickets today and queued tickets
   - GitHub open PRs and merged PRs within 24h
   - Empirical estimation summary in minutes
3. Ensure governance check passes with 0 errors and test suite passes with exit code 0.

## Acceptance criteria

- [x] AC-01: `_find_subllm_runner` invokes SubLLM with proper application and function parameters.
- [x] AC-02: `monag summary` CLI command aggregates completed tickets, backlog queue, open PRs, and merged PRs.
- [x] AC-03: `monag summary --json` returns structured daily metric summary.
- [x] AC-04: Test coverage verifies SubLLM runner and summary aggregation.
- [x] AC-05: Test suite and `./project/governance-check.sh` pass.

## Session authorization

User explicit request "kolejno" authorizing execution of proposed improvements treated as SESSION_EXECUTION_AUTHORIZATION.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
