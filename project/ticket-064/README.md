# Ticket 064: delegate conflict and duplicate detection to semcod/algocode

- **ID**: ticket-064
- **Owner**: agent
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-09-18

## Goal and scope

Delegate duplicate detection and workstream conflict verification in `monag.advise` to the deterministic algorithmic engine `semcod/algocode`.

## Acceptance criteria

- [x] AC-01: Implement `_find_algocode_runner()` and `collect_algocode_evidence()` in `monag.advise`.
- [x] AC-02: Integrate deterministic path collision and branch conflict checking via `algocode.engine.check_conflict` into advisory synthesis.
- [x] AC-03: Add unit tests in `tests/test_advise.py` covering algocode delegation when available and graceful fallback when absent.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
