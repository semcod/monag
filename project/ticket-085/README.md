# Ticket 085: autodiagnosis-subllm-planfile-pipeline

- **ID**: ticket-085
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-25

## Goal and scope

1. Create a fleet autodiagnosis engine (`monag.autodiagnosis`) that inspects workspace repositories for technical defects, missing standard files, uncommitted changes, dependency/package drift, and missing Planfile/GitHub sync configurations.
2. Integrate SubLLM synthesis to analyze observed anomalies, formulate root causes, and generate actionable tickets complete with Acceptance Criteria (`AC-01`, `AC-02`), verification test commands, and Koru Autonomous execution handoffs (`planfile ticket done`, git discipline).
3. Implement deterministic fallback ticket generation when SubLLM is offline or unconfigured.
4. Implement Planfile sprint dispatching that safely formats and writes tickets directly into target repositories' `.planfile/sprints/{sprint}.yaml` storage, formatted for bidirectional `planfile sync github` and execution by `koru autonomous`.
5. Expose the `autodiagnose` subcommand in `monag.cli` with options `--subllm`, `--no-subllm`, `--emit-planfile`, and `--feed-planfile`.
6. Add comprehensive unit and integration test coverage (`tests/test_autodiagnosis_subllm_pipeline.py`).

## Acceptance criteria

- [x] AC-01: `diagnose_fleet()` inspects repositories and identifies technical anomalies (missing README/LICENSE, dirty worktrees, dependency git URLs, uninitialized Planfile).
- [x] AC-02: `synthesize_tickets_with_subllm()` generates structured Planfile/GitHub/Koru tickets with AC criteria and verification commands via SubLLM runner.
- [x] AC-03: Rule-based deterministic fallback ensures robust ticket synthesis when SubLLM runner is unavailable or fails.
- [x] AC-04: `dispatch_tickets_to_planfile()` writes synthesized tickets into target projects' `.planfile/sprints/{sprint}.yaml`, ensuring idempotency and correct schema.
- [x] AC-05: Tickets conform to `planfile sync github` schema and Koru Autonomous handoff contracts (`koru.queue` / `koru.autonomy.planfile_handoff`).
- [x] AC-06: `monag autodiagnose` CLI subcommand supports `--emit-planfile` and `--feed-planfile` modes.
- [x] AC-07: Full test suite passes.
