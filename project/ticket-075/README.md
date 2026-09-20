# ticket-075 — Persist triage feed per project

- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Owner**: codex:monag-triage-cache-20260919

SESSION_EXECUTION_AUTHORIZATION: execute confirmed report/cache defects; Planfile PLF-027, GitHub sync pending quota reset.

Scope: persist deduplicated Planfile records in each existing owning project, validate paths, report actual IDs and partial failures. No implicit remote sync or allocation of implementation ownership.

- [x] AC-01: Feed persists and reads back project-local ticket IDs using native Planfile.
- [x] AC-02: Repeat feed deduplicates; missing projects/dependencies and partial failures are truthful.
- [x] AC-03: CLI output reflects persisted results; full tests/governance pass.

Validation: 343 full pytest tests and 19 focused triage/feed tests pass. Native installed Planfile persisted two separate project-local IDs and returned those same IDs on repeat. Governance, Ruff and whitespace checks pass.
