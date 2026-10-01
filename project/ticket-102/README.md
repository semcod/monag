# Ticket 102: monag drift: SSOT fact checker comparing declared owners with deployed copies

- **ID**: ticket-102
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-01

## Goal and scope

`monag drift --spec FILE` is a read-only single-source-of-truth check. Every
fact names one owner (an OQL/env/quadlet file or an HTTP JSON field) and its
copies; each copy is reported `match`, `mismatch` or `unavailable`, and the
exit code is 1 on any mismatch. It was requested after one day on the
Maskservice rig in which the same pump pins, firmware profile, Tic polarity
and service URLs lived in several files and devices and drifted apart.

## Acceptance criteria

- [x] AC-01: OQL `SET`, dotenv, quadlet `Environment=` and HTTP JSON sources; files also over SSH (`cat` only).
- [x] AC-02: Unreadable copies are `unavailable`, not drift; relative paths resolve against the spec file.
- [x] AC-03: Markdown and JSON output; `tests/test_drift.py` covers match, stale copy, offline copy, validation and CLI exit code.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
