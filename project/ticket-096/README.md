# Ticket 096: Fix procache optional fallback and improve cli entrypoint

- **ID**: ticket-096
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

1. Guard `procache` import in `src/monag/cache.py` so that missing `procache` does not raise `ModuleNotFoundError`, ensuring graceful fallback (`PROCACHE_AVAILABLE = False`).
2. Ensure `src/monag/cli.py` has an executable entrypoint `if __name__ == '__main__': raise SystemExit(main())` so `python3 -m monag.cli` behaves identically to `python3 -m monag` and `monag`.
3. Add unit tests for `cache.py` graceful fallback and CLI entrypoint in `tests/test_procache_integration.py`.

## Acceptance criteria

- [x] AC-01: `src/monag/cache.py` gracefully catches `ImportError` / `ModuleNotFoundError` when `procache` is not installed, setting `PROCACHE_AVAILABLE = False`.
- [x] AC-02: `src/monag/cli.py` includes standard `__main__` entrypoint guard.
- [x] AC-03: Unit tests in `tests/test_procache_integration.py` verify graceful cache fallback and CLI execution without errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
