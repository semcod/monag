# Ticket 086: monag serve alias for panel

- **ID**: ticket-086
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-25

## Goal and scope

1. Add `serve`, `dashboard`, and `ui` as first-class aliases for the `monag panel` command in `src/monag/cli.py`.
2. Ensure `monag serve` shares identical arguments, options, defaults, validation, and execution behavior with `monag panel`.
3. Add unit tests in `tests/test_cli.py` verifying that `serve`, `dashboard`, and `ui` invoke the panel server handler properly.

## Acceptance criteria

- [x] AC-01: `sub.add_parser('panel', aliases=['serve', 'dashboard', 'ui'], ...)` is configured in `src/monag/cli.py`.
- [x] AC-02: Argument validation and CLI execution routes `serve`, `dashboard`, and `ui` to the panel server.
- [x] AC-03: Tests in `tests/test_cli.py` verify that `monag serve` is accepted and recognized with matching configuration.
- [x] AC-04: Full test suite passes and governance validation passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
