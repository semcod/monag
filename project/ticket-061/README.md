# Ticket 061: monag report: include architectural advisory and autogrammar contract guardrails

- **ID**: ticket-061
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested continuation of monag advise/report integration with autogrammar and reflex)

## Goal and scope

1. Integrate the `advise` engine into `monag report` so that periodic/email digests include prioritized architectural guidance, risk patterns, and next-task guardrails.
2. Optimize execution by allowing `advise()` to reuse pre-scanned `export` candidates in `report.collect()` to prevent redundant filesystem traversal.
3. Enhance `src/monag/advise.py` with autogrammar contract awareness (e.g. `autogrammar/intract`, `code2schema`, grammar/DSL schemas).
4. Expose `--advisory-limit` CLI flag in `monag report`.
5. Maintain 100% test coverage and zero external dependencies (Python standard library only).

## Acceptance criteria

- [x] AC-01: `src/monag/advise.py` accepts `export_data` parameter to avoid duplicate workspace scanning.
- [x] AC-02: `src/monag/advise.py` recognizes contract/schema/grammar keywords and generates `autogrammar/intract` guardrails.
- [x] AC-03: `src/monag/report.py` registers `advise` in `SECTION_REGISTRY`, `_SECTION_FORMATTERS`, and `_SECTION_TITLES`.
- [x] AC-04: `format_section_advise()` formats advisory table and actionable guardrails for email/markdown.
- [x] AC-05: `monag report` CLI supports `--advisory-limit` and includes advisory recommendations when requested.
- [x] AC-06: Comprehensive unit tests pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
