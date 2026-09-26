# Ticket 093: add holistic triage and collision monitor view in panel

- **ID**: ticket-093
- **Owner**: antigravity:ticket-093
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

Integrate holistic triage guidance and multi-agent worktree collision monitoring into `monag serve` (Panel):
1. In `src/monag/panel.py`:
   - Add state and API endpoints (`/api/triage.json`, `/api/collisions.json`) exposing active agent fleet processes, dirty worktrees, declared scope collisions, and synthesized sequential guidance steps.
   - Render a dedicated "Holistic Triage & Guidance" dashboard section in the Panel HTML UI:
     - Collision warnings and active agent locks (agent type, PID, worktree).
     - Categorized priority queues with safety badges (`Ownership unverified`, `⚠️ Declared conflict / active agent`).
     - Interactive `⚡ dispatch to koru` action for triage recommendation steps.
2. Ensure live auto-refresh updates triage and collision telemetry without page reload.
3. Add unit test coverage and ensure governance check passes with `GOV-PASS`.

## Acceptance criteria

- [x] AC-01: `/api/triage.json` returns holistic triage guidance and collision metadata.
- [x] AC-02: Panel HTML dashboard renders the Holistic Triage & Collision Monitor section.
- [x] AC-03: Collision badges and agent process warnings display prominently in the UI.
- [x] AC-04: Unit tests pass and `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
