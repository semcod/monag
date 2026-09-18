# Ticket 060: monag advise: architectural guidance and next task recommendations based on reflex

- **ID**: ticket-060
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested advising and task guidance based on subactor/reflex and ecosystem tooling)

## Goal and scope

Add `monag advise` subcommand and advisory engine:
1. Ingest workspace candidates from `export.scan`
2. Integrate `subactor/reflex` failure patterns and improvement proposals (governance, tool-contract, rate-limit, dependency drift)
3. Synthesize prioritized next tasks with actionable guidelines, rationale, and guardrails for human developers and autonomous agents
4. Integrate with CLI (`monag advise`), interactive shell (`advise`), HTTP panel (`/api/advise.json`), and MCP server (`monag_advise`)
5. Fix missing `import os` in `src/monag/prs.py`

## Acceptance criteria

- [x] AC-01: `src/monag/advise.py` implements `advise(root, ...)` combining candidate export, reflex patterns, and prioritization.
- [x] AC-02: Generates structured guidance including action, rationale, guardrails, and complexity.
- [x] AC-03: Graceful degradation when `reflex` is not available or no log sources exist.
- [x] AC-04: CLI `monag advise` supports `--format`, `--json`, `--markdown`, `--radar`, `--reflex-source`.
- [x] AC-05: Integrated in interactive shell, web panel, and MCP tool registry.
- [x] AC-06: Comprehensive unit tests pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
