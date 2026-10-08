# Ticket 107: Infer an agent's task from the ticket worktree it works in

- **ID**: ticket-107
- **Owner**: claude-code
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-08

## Goal and scope

`monag status` listed every agent as `task: unknown (process only)` unless it was started through `monag run`, so it could not answer whether work is progressing autonomously. When no task was reported, infer it from a canonical `.worktrees/ticket-NNN--slug` working directory of the agent or its children and show the ticket intent summary, labelled as inferred. User authorization: investigate with monag/reflex and continue fixing (`kontynuuj`).

## Acceptance criteria

- [ ] AC-01: Agents without a reported task but working in a ticket worktree show `inferred from worktree: <repo> ticket-NNN: <summary>`; others stay `unknown (process only)`; reported tasks win.
- [ ] AC-02: Tests and governance pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
