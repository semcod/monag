# Ticket 084: fix-broken-git-marker-error-reporting-and-cli-subcommand-options

- **ID**: ticket-084
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-24

## Goal and scope

1. Enhance `monag.monitor.discover()` to report observation errors on invalid `.git` directories (missing HEAD) while continuing traversal into descendant repositories, while keeping graceful skipping of broken `.git` worktree pointer files without observation errors.
2. Propagate common flags (`--limit`, `--hours`, `--github`, `--open-files`, `--agents-only`, `--machine`) across all CLI subparsers in `monag.cli` so that subcommand invocations such as `monag resume --limit 20` or `monag history --hours 10` work without argument parsing failures.

## Acceptance criteria

- [x] AC-01: `discover()` reports an error when encountering an invalid `.git` directory missing `HEAD` while still exploring descendant repositories.
- [x] AC-02: `discover()` gracefully ignores broken `.git` worktree pointer files whose `gitdir` target does not exist without exit 128 observation errors.
- [x] AC-03: Subcommands in `monag.cli` accept `--limit`, `--hours`, and other top-level flags.
- [x] AC-04: Full test suite passes.
