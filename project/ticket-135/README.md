# Ticket 135: bound autodiagnosis subllm synthesis budget and discover default drift spec

- **ID**: ticket-135
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Goal and scope

1. Bound SubLLM synthesis in `src/monag/autodiagnosis.py` with a non-blocking per-call timeout (`MONAG_SUBLLM_TIMEOUT_SECONDS`), total wall-clock synthesis budget (`MONAG_AUTODIAG_LLM_BUDGET_SECONDS`), and consecutive-failure circuit breaker (`MONAG_SUBLLM_MAX_FAILURES`), falling back deterministically to `_parse_subllm_response`.
2. Support configurable Planfile queue target via `MONAG_PLANFILE_QUEUE` (defaulting to `default`).
3. Add `resolve_spec_path` in `src/monag/drift.py` and make `--spec` optional in `src/monag/cli.py` so `monag drift` discovers `$MONAG_DRIFT_SPEC`, `~/.config/monag/drift.json`, `<root>/.monag/drift.json`, or `<state-dir>/drift.json`.
4. Add unit tests in `tests/test_autodiagnosis_subllm_pipeline.py` and `tests/test_drift.py`.

## Acceptance criteria

- [x] AC-01: `synthesize_tickets_with_subllm` bounds slow/hung SubLLM calls and trips the circuit breaker into deterministic fallback within budget.
- [x] AC-02: `monag drift` discovers default `monag.ssot-drift/v1` specs when `--spec` is omitted and exits 2 cleanly when none exist.
- [x] AC-03: Unit tests and repository governance checks pass with exit code 0.
