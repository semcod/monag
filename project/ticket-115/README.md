# Ticket 115: Serialize fleet autodiagnosis without internal database handles

- **ID**: ticket-115
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous analysis and repair across MONAG, Reflex, Willman and Willmux. The observed JSON CLI crashes on the internal SQLite Connection stored in its diagnosis dictionary, preventing machine consumers from receiving observations. Preserve cache processing while emitting only public diagnosis fields; release the CLI-owned connection after synthesis.

## Acceptance criteria

- [x] AC-01: autodiagnose JSON output parses with cached and uncached reports and excludes private implementation fields.
- [x] AC-02: Ticket synthesis can use the live cache connection; the CLI releases it after success or synthesis failure.
- [ ] AC-03: Regression tests and managed governance pass; publish through independent review and verify a fresh machine-readable observation.

## Validation

- 28 related CLI/cache/synthesis tests passed; all 5 focused regressions passed after adding `--no-cache`. Governance and diff checks passed.
- `--no-cache` forces fresh diagnosis collection for observation consumers; cached reports cannot establish current device or service state.
- Independent publication and deployed observation remain pending under AC-03.
