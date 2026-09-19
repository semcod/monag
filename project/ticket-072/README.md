# Ticket 072: Adopt subactor-procache for GitHub API read caching

- **ID**: ticket-072
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19

## Goal and scope

Integrate subactor-procache to cache read-side GitHub API commands (e.g. pr list, repo view, issue list, api GET) and prevent secondary rate limits via shared SQLite and provider cooldowns.

## Acceptance criteria

- [x] AC-01: Read-side gh commands are cached via SQLiteResponseCache and CachedReadCommand.
- [x] AC-02: Mutating gh commands bypass the cache and execute directly.
- [x] AC-03: Provider 429 rate limits trigger cooldown and avoid request storms.
- [x] AC-04: Graceful fallback when procache is unavailable or disabled.

## Validation

All unit and integration tests pass with 100% green coverage, including tests for cache hit/miss, mutating command bypass, rate-limit cooldown, and environment override.
