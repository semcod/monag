# Ticket 113: Agent process visibility

- **ID**: ticket-113
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-11

## Goal and scope

Read identity metadata for every observed process, then resolve working directories only for recognized/reported agents and their descendants. Unrelated services with restricted cwd links must not falsely invalidate agent attribution. Missing metadata or denied cwd in an agent tree remains an incomplete observation. Preserve the existing recognized-agent policy, privacy boundary and protected admission gate.

SESSION_EXECUTION_AUTHORIZATION: user explicitly approved repairing Monag as part of autonomous Willman multi-project execution and protected merging. Invoke local OneDev and independent Validator for publication; this note is not merge approval.

## Acceptance criteria

- [x] AC-01: Unrelated cwd denial does not discard readable identity data or falsely block agent observation.
- [x] AC-02: Recognized and reported agents, child processes, and inaccessible metadata remain fail-closed; grouping and attribution stay correct.
- [ ] AC-03: Regression/full tests and managed governance pass; a real host scan and independent protected publication verify the change.

## Bounds

maxActiveMinutes: 120; checkpointMinutes: 30. Only monitor.py and its tests are implementation scope; no privilege or admission policy changes.

Validation: 498 passed, 1 skipped, 42 subtests passed; governance 0 errors/0 warnings. Host scan detected 19 agents with zero inaccessible relevant processes. Protected publication remains pending.
