# ticket-073 — Evidence-based triage recommendations

- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Owner**: codex:monag-triage-cache-20260919

SESSION_EXECUTION_AUTHORIZATION: user asked to execute the screenshot recommendations. Correct confirmed recommendation defects before selecting work; Planfile PLF-026, GitHub Issue89.

Scope: distinguish observed leases and checkouts from verified activity/collisions; retain unknown ownership; generate read-only next steps until publication and ownership evidence are available. No takeover, automatic Issue closure or merge from heuristic ranking.

- [x] AC-01: Terminal, malformed and missing leases retain accurate evidence.
- [x] AC-02: Registered worktrees and ancestry differences do not prove active work or remote publication.
- [x] AC-03: Missing CI or ownership does not produce a safe/merge-ready claim.
- [ ] AC-04: Regressions, full tests and governance pass; publish through protected review.

Validation: 339 pytest tests passed with installed procache dependency and 4 subtests; no skipped cache integration tests. Triage regressions re-run after primary lease resolution change; governance and scoped Ruff pass. Publication remains pending protected review.
