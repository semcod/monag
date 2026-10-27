# Ticket 131: Cache explicit GitHub API reads from repository monitors

- **ID**: ticket-131
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — the user requested reusable caching of repeated API records across providers and investigation of missed call paths.

## Goal and scope

Reuse canonical Procache for explicit GitHub API reads from repository monitors while preserving cwd-dependent execution and zero-TTL bypass. Preserve unrelated primary integration changes.

## Acceptance criteria

- [x] AC-01: Explicit API and repository read commands reuse cache; implicit repository context and placeholders retain direct execution.
- [x] AC-02: Cache/monitor regressions and managed governance pass; failures never trigger duplicate transport calls.
- [ ] AC-03: Observe protected publication separately from local checks and runtime deployment.

Local verification: 42 scoped cache and monitor tests pass, with sixteen additional subtests, against the accepted canonical Procache source. Governance and scoped lint pass. No provider request is repeated after a cache/transport failure.

The five context regression methods also pass under unittest discovery, matching the deployed protected Monag test collector. Existing accepted Procache emits SQLite ResourceWarnings; this ticket does not hide or change that dependency behavior.
