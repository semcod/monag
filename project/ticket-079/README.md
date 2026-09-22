# Ticket 079: cli-parser-subcommand-options-and-version

- **ID**: ticket-079
- **Owner**: human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-22

## Goal and scope

Enhance `monag` CLI argument parser to support standard `--version` reporting at the root level and enable common options (`--root`, `--state-dir`, `--depth`, `--format`, `--json`, `--markdown`, `--plain`) after subcommands (e.g. `monag status --root /path --json`). In addition, isolate `tests/test_resume.py` git configuration (`core.excludesfile`) so tests run hermetically regardless of host user `.config/git/ignore` settings.

## Acceptance criteria

- [x] AC-01: Add `--version` flag to root CLI parser displaying `monag <version>`.
- [x] AC-02: Support common arguments (`--root`, `--state-dir`, `--depth`, `--format`, `--json`, `--markdown`, `--plain`) passed after subcommands.
- [x] AC-03: Isolate test git repo configuration in `tests/test_resume.py` against user `core.excludesfile`.
- [x] AC-04: Unit tests for `--version` and trailing subcommand options pass.
- [x] AC-05: Full test suite (386 tests) and governance check pass with `GOV-PASS`.

## Validation

All 386 tests in pytest suite pass. Governance check passes with 0 errors, 0 warnings.
