# Ticket 132: Classify historical Planfile validation errors separately from canonical admission failures

- **ID**: ticket-132
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-28
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — user requested further diagnosis and actionable owner-project tickets (semcod/monag#155, PLF-20344).

## Goal and scope

Classify historical Planfile validation errors separately from canonical admission failures in `src/monag/resume.py`. Ensure valid canonical tickets with unchanged inherited copies or historical snapshots yield explicit historical diagnostics and correct canonical readiness, while keeping malformed canonical data, changed peer stores, unresolved identities, and conflicts blocking.

## Acceptance criteria

- [x] AC-01: Valid canonical ticket plus unchanged malformed inherited copy yields explicit historical diagnostics and correct canonical readiness (`complete: True`, empty blocking errors in project observation).
- [x] AC-02: Malformed canonical data, changed peer stores, unresolved identities, and conflicts remain blocking (`complete: False`, blocking errors retained in project observation).
- [x] AC-03: Historical diagnostics are explicitly retained in `project['historical_diagnostics']` and `project['planfile']['historical_diagnostics']` without blanket suppression or modifying historical snapshots.
- [x] AC-04: Existing consumers (`audit`, `report`, `export`, `panel`, `cli`) and schemas retain backward compatibility.

## Consumer compatibility evidence

- `monag resume --json`: `project['errors']` contains only blocking admission failures so external intake runners (such as Heyasa campaign job658986eb-71d7-4844-bb92-05eec87095b0) do not refuse projects on inherited legacy backlog errors; historical diagnostics are explicitly provided under `project['historical_diagnostics']` and `project['planfile']['historical_diagnostics']`.
- `monag.resume.planfile()`: returns `(result, sources, errors)` where errors remain string-compatible (`PlanfileDiagnostic(str)`), preserving contracts with `monag.audit` and test fixtures.
- `monag.export` and `monag.report`: consume `project['planfile']['remaining_tickets']` unchanged.
- `monag.panel`: renders `/api/resume.json` ticket table and checkouts without schema drift.
