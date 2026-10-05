# Ticket 104: feat(autodiagnosis): system log inspection for willman/willmux defects and opencode planfile execution

- **ID**: ticket-104
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-05

## Goal and scope

Enhance workspace autodiagnostics in `monag.autodiagnosis` to:
1. Inspect runtime system logs of `willman` (`.willman/logs/daemon-*.log`, `*.ndjson`) and `willmux` (`~/.config/willmux/agent-log.jsonl`, `events.jsonl`) for errors, uncaught exceptions, and task execution failures.
2. Emit classified `SYSTEM_LOG_ERROR` anomalies with high fidelity and proper priority tiers (`TIER_FLOOR` or `TIER_MISSION`).
3. Synthesize actionable defect-repair tickets for detected system log anomalies.
4. Route synthesized tickets to target projects' Planfile sprints with OpenCode runner configuration (`contract: "wellmanifest.defect-repair/v1"`, `patch_mode: true`, `worktree: true`, `provider: "opencode"`).
5. Ensure bidirectional synchronization with GitHub Issues via `planfile sync github`.

## Acceptance criteria

- [x] AC-01: `inspect_repository_anomalies` inspects system service logs for `willman` and `willmux` and generates `SYSTEM_LOG_ERROR` anomalies.
- [x] AC-02: Ticket synthesis maps `SYSTEM_LOG_ERROR` anomalies to concrete actions, acceptance criteria, and verification commands.
- [x] AC-03: `dispatch_tickets_to_planfile` configures OpenCode runner directives (`provider: "opencode"`, `patch_mode: true`) for defect repair.
- [x] AC-04: Full automated test suite passes with 100% green and governance checks pass with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
