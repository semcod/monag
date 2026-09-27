# Ticket 099: add conversational voice and nl assistant to monag panel

- **ID**: ticket-099
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-27

## Goal and scope

Add a conversational voice (Web Speech API) and natural-language assistant to the Monag HTTP
dashboard (`monag panel` / `monag serve`). Integrate Option Network quick-action suggestion pills,
real-time query answering from live in-memory telemetry, and Polish/English speech-to-text input
to monitor fleet agents, triage, autodiagnosis, and Planfile tickets.

## Acceptance criteria

- [x] AC-01: Conversational UI added to `src/monag/panel.py` with responsive layout, Option Network pills, and voice input.
- [x] AC-02: Web Speech API microphone integration with Polish (`pl-PL`) support, acoustic visual indicators, and auto-dispatch.
- [x] AC-03: `/api/assistant` endpoint serving instant answers for agents, triage, autodiagnosis, tickets, and PRs from live state.
- [x] AC-04: Enhanced intent parser in `src/monag/dsl.py` supporting conversational Polish/English queries.
- [x] AC-05: Unit and integration tests in `tests/test_panel_conversational_assistant.py` passing cleanly with zero governance errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
