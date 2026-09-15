# ticket-023 — Serve candidate-work export from monag panel

- **ID**: ticket-023
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add `/api/export.json` to `monag panel` and a matching dashboard section,
so the candidate-work list (`audit-untracked-issue`, `catalog-undescribed`,
`taskill-doc-drift`) is visible in the live panel — completing the
"proactive, at-a-glance" dashboard originally requested, now that
`export` (ticket-006/020/021) exists to show.

Served without `--radar`/`--hygiene`: both shell out per candidate or
per repository, which would make the panel's on-demand refresh slow;
use `monag export --radar --hygiene` directly for the enriched report.

## Acceptance criteria

- [x] AC-01: `/api/export.json` returns the same shape as `monag --json
      export`, lazily computed and cached (matching the existing
      `/api/audit.json`/`/api/catalog.json` TTL-cache pattern).
- [x] AC-02: The panel never requests `--radar`/`--hygiene` on its own
      (`radar_requested`/`hygiene_requested` are always `false` there).
- [x] AC-03: The dashboard HTML has a "Candidate work" section with a
      refresh button, consistent with the existing audit/catalog sections.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
