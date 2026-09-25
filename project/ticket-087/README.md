# Ticket 087: sqlite persistent autodiagnosis and semcod estimation

- **ID**: ticket-087
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-25

## Goal and scope

1. Create persistent SQLite storage for fleet autodiagnosis (`src/monag/autodiag_store.py`) to record repository state fingerprints (`head_sha`, `dirty_digest`, `mtime`), cached anomalies, and synthesized tickets.
2. Implement incremental caching: if a repository's Git state fingerprint has not changed since the last diagnostic run, reuse existing records from SQLite and skip redundant SubLLM synthesis.
3. Integrate `semcod/estimation` empirical process metrics (duration p50/p90, peak RSS bytes, effective CPU cores, sample count, confidence) into synthesized tickets and Planfile sprint task descriptions.
4. Expose estimation metrics in CLI (`monag autodiagnose`) and web panel (`monag serve` / `GET /api/autodiagnosis.json`).
5. Ensure idempotent Planfile dispatch: do not duplicate or overwrite existing tasks if the technical defect fingerprint is unchanged.
6. Add comprehensive unit and integration test coverage (`tests/test_autodiag_store.py` and `tests/test_estimation_integration.py`).

## Acceptance criteria

- [x] AC-01: SQLite store (`autodiag_store.py`) tracks repository fingerprints and persists anomalies and tickets.
- [x] AC-02: `diagnose_fleet()` reuses cached diagnostic results when a repository's Git state and working tree are unchanged.
- [x] AC-03: `synthesize_tickets_with_subllm()` queries `semcod/estimation` historical process samples and attaches empirical resource envelopes (duration, peak RSS, CPU, confidence).
- [x] AC-04: Synthesized tickets contain Markdown section `## Empirical Resource Estimation (semcod/estimation)` and structured `estimation` dictionary.
- [x] AC-05: Web panel and REST endpoints reflect estimation metadata and SQLite cache status.
- [x] AC-06: All tests pass and `./project/governance-check.sh` reports `GOV-PASS`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
