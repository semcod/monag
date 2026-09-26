# Ticket 092: agent worktree collision detection and holistic fleet guidance

- **ID**: ticket-092
- **Owner**: antigravity:ticket-092
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

Implement multi-agent worktree and lease collision detection and an enhanced holistic
workspace guidance engine in `monag.triage` and `monag.advise` (Issue #68):
1. Audit active agent processes (PIDs, kinds: `koru`, `claude-code`, `codex`, `gemini`, etc.)
   and check whether agent processes are running in repository worktrees.
2. Audit dirty worktrees and pending deltas under `<primary>/.worktrees/`.
3. Support the 5 actionable categorization classes from Issue #68:
   - Immediate Blockers
   - Core / Personal repository backlogs
   - Strategic / architectural issues
   - Operator and IDE integration alerts (MCP bootstrap, Planfile API)
   - Fleet health diagnostics
   - Code-smell hygiene queues
4. Synthesize conflict-free, step-by-step sequential guidance adhering to
   Wellmanifest Worktrees v5 policy.

## Acceptance criteria

- [x] AC-01: `audit_active_fleet_processes` detects running autonomous agents and their active directories.
- [x] AC-02: `check_agent_collision` detects active process occupation, dirty worktrees, and active leases.
- [x] AC-03: `classify_candidate` categorizes pending issues into actionable classes with collision penalty.
- [x] AC-04: Guidance synthesis outputs conflict-safe sequential steps.
- [x] AC-05: Unit tests pass and governance check yields GOV-PASS.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
