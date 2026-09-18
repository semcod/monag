# Ticket 066: feat(advise): planfile ticket generator and overall PR/worktree overview metrics

- **ID**: ticket-066
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested planfile ticket generator from monag recommendations, plus overall workspace PR and worktree counts in advisory tables)

## Goal and scope

1. **Planfile Ticket Generator & Importer Integration:**
   - Add `to_planfile_ticket(rec)` in `monag.advise` to map candidate recommendations to standard `planfile` tickets (title, description, mapped Priority DSL priority, labels, satisfied_when, target_repo).
   - Add `export_planfile_tickets(advisory_data, tier=None)` returning structured `{"tickets": [...]}` compliant with `planfile ticket import`.
   - Add `feed_to_planfile(advisory_data, root, sprint="current", tier=None)` executing `planfile ticket import --source monag` via subprocess or stdin.
   - Expose `--emit-planfile` and `--feed-planfile` in `monag advise` CLI and MCP tool `monag_advise`.

2. **Overall PR and Worktree Metrics in Presentation Tables:**
   - Include `total_prs` and `total_worktrees` metrics in `advisory_data`.
   - In `monag.advise.markdown()`, render an Executive Overview table presenting:
     `| Otwarte PR (GitHub) | Aktywne Worktrees | Rekomendacje (Floor / Mission / Hygiene) |`
   - In `monag.report.markdown()`, render a high-level overview table at the top of the report:
     `| Otwarte PR | Aktywne Worktrees | Zadania Planfile | Rekomendacje Advise |`

3. **Governance & Tests:**
   - 100% test pass rate across unit and integration tests.
   - Passes `governance-check.sh`.

## Acceptance criteria

- [ ] AC-01: `to_planfile_ticket()` maps recommendation fields to Planfile-compliant ticket dicts with mapped priorities and labels.
- [ ] AC-02: `export_planfile_tickets()` outputs `{"tickets": [...]}` compatible with `planfile ticket import`.
- [ ] AC-03: `advise()` and `markdown()` compute and display total workspace PR and worktree counts in overview tables.
- [ ] AC-04: `monag advise` CLI supports `--emit-planfile` and `--feed-planfile`.
- [ ] AC-05: `monag report` displays executive summary metrics table with PRs and Worktrees.
- [ ] AC-06: Unit tests cover Planfile ticket conversion, CLI flags, and metric table presentation.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
