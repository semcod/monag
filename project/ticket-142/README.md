# Ticket 142: Align procache integration tests with credential-bound caching

- **ID**: ticket-142
- **Owner**: agent:claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Authorization

`SESSION_EXECUTION_AUTHORIZATION` recorded from the operator's session
requests ("zbadaj semcod/monag, diagit i subactor/reflex … naprawiaj błędy",
"kontynuuj, wykonaj, scalaj").

## Allocation note

The allocator scaffolded `project/ticket-142` in the primary checkout and added
index rows there; the directory was moved unchanged to the Worktrees v5
location from `.governance/worktree_path_check.py plan`, and the primary
checkout was restored to its prior state.

## Goal and scope

`tests/test_procache_integration.py` failed (8 tests/subtests) on untouched
`main` whenever `procache` is installed. dockuri/procache ticket-013 binds a
shared cached `gh` response to a provable credential scope: an explicit token
plus host for `gh api`, or both public and enterprise tokens for other read
commands. The tests ran without any token, so every read executed twice.

Pin that scope in the test fixture and `CacheContextTests` with placeholder
tokens, `GH_HOST` and an isolated `GH_CONFIG_DIR`, and add a test that reads
are never shared when the scope is unprovable. No source change.

## Acceptance criteria

- [x] AC-01: `tests/test_procache_integration.py` passes with procache installed.
- [x] AC-02: A new test asserts unprovable credential scope executes every read.
- [x] AC-03: Full pytest (613 passed), ruff and `./project/governance-check.sh` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
