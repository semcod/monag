# Ticket 101: Accurately probe HTTP service titles and label Planfile queue on 8765

- **ID**: ticket-101
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-28

## Goal and scope

Improve HTTP API / Web service probing in `src/monag/ecosystem.py`:
1. Port 8765 is the Planfile Queue Web Panel (`subactor tickets` / `planfile queue`), not Monag. Correct the default mapping.
2. Implement dynamic `<title>` inspection for listening local HTTP services so that the real HTML title (e.g. `planfile queue`, `SubLLM · Użycie API`, `taskand · kontekst i stan live`) is extracted and used as the service label.
3. Keep Monag Web Panel on default port 8090 while allowing dynamic discovery.

## Acceptance criteria

- [x] AC-01: Update `src/monag/ecosystem.py` to map port 8765 to Planfile Queue Panel.
- [x] AC-02: Add dynamic HTTP title probing with short timeouts for listening ports.
- [x] AC-03: Update tests in `tests/test_ecosystem_tools.py` verifying accurate service naming.
- [x] AC-04: All tests pass and governance passes with zero errors (`GOV-PASS`).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
