# ticket-117 — Non-executing discovery and bounded publication retries

- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Agent**: codex

Authorization: SESSION_EXECUTION_AUTHORIZATION — continue Monag/Reflex optimization and repair of recurring Maskservice system errors, tests and independent publication. GitHub adoption only; on-premise audit only.

## Outcome
Read-only ecosystem discovery currently starts arbitrary discovered executables with --version. A controlled harmless PATH fixture reproduced this behavior. Read static package metadata instead, leave unknown versions unknown, and isolate ecosystem tests from real host tools/services. Preserve the genuine unpublished rate-limit batch deferral from archived ticket-116.

## Acceptance
- AC-01: Unknown discovered executables cannot run, including side-effecting version fixtures. Known package versions come from metadata; availability/path inventory remains intact. Tool and local-service tests use isolated fixtures.
- AC-02: API or adapter rate limits defer remaining batch calls without transport fallback. Existing exact-head publication, historical verification and wrong-head/digest refusals remain covered.
- AC-03: Focused tests, complete suite as bounded by NoLimits, Testless advisory planning, lint, native governance and protected OneDev pass; only the independent Validator may approve and merge.

## Provenance
Another writer committed and owner-merged ticket-116 as PR #139 without reviews while this agent still held its editing lease. Its later genuine material commit 8c34bc8fa33b89aa831e9af84d72a75708491e26 was omitted. The exact commit, verified bundle and two-file material patch are preserved externally. Use an accepted fenced handoff through the existing controller into this newly allocated ticket, never reuse integrated ticket-116 or invent approval evidence.

## Validation
The complete local suite passed: 520 tests, one skipped and 47 subtests in 263.83s (268.772s including preflight). The previous full attempt was interrupted after 326.96s with only 156 tests passed; it is not a complete baseline timing. Focused discovery/publication/MCP checks passed 45 tests and five subtests. Ruff 0.15.11, native governance and focused Testless passed; advisory plans remain external.

The controlled unknown-program fixture started under the old scanner (0.170806s) and did not start under this candidate (0.000054s). This demonstrates removal of executable startup, not a production-wide speed ratio. Distribution metadata is accepted only when its RECORD owns the observed file; an unrelated installed version is not assigned to another CLI. Existing required OneDev unittest/build verification is unchanged.

The canonical worktree is Git-locked while this owner is active following the recorded concurrent removal of ticket-116. Controller handoff and new fencing are recorded externally. No evidence attributes the earlier real owner merges to the inventory probe.
