# Ticket 091: add live auto-refresh and dispatch to koru in panel

- **ID**: ticket-091
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

1. Add live telemetry auto-refresh in `src/monag/panel.py` dashboard:
   - Configurable auto-refresh toggle (default enabled, 15s interval) and countdown badge in the UI.
   - Smooth asynchronous polling that refreshes agents, projects, and autodiagnosis state without full page reload.
2. Add "Dispatch to Koru" integration in web panel:
   - Implement `POST /api/autodiagnosis/dispatch-koru.json` in `src/monag/panel.py`.
   - Dispatch synthesized tickets directly to the target project's Planfile and notify the active Koru daemon.
   - Add UI buttons: "Dispatch to Koru" per ticket and "Dispatch All to Koru" in the autodiagnosis header.
3. Validate with unit tests in `tests/test_panel_dispatch_koru_and_autorefresh.py` and ensure `./project/governance-check.sh` passes.

## Acceptance criteria

- [x] AC-01: Panel UI includes auto-refresh toggle and client-side periodic refresh without page reload.
- [x] AC-02: `POST /api/autodiagnosis/dispatch-koru.json` endpoint dispatches synthesized tickets to Planfile and marks for Koru autonomous execution.
- [x] AC-03: UI renders interactive "Dispatch to Koru" buttons with instant feedback toast.
- [x] AC-04: Test coverage validates auto-refresh metadata and dispatch-koru endpoint.
- [x] AC-05: Test suite and `./project/governance-check.sh` pass.

## Session authorization

User explicit request "kolejno" authorizing execution of proposed improvements treated as SESSION_EXECUTION_AUTHORIZATION.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
