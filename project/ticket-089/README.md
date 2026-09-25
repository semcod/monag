# Ticket 089: advanced autodiagnosis anomalies, github issues sync and panel badges

- **ID**: ticket-089
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-25

## Goal and scope

1. Fix CLI invocation in `src/monag/cli.py` to pass full `diag_report` into `synthesize_tickets_with_subllm`, enabling persistent SQLite caching of synthesized tickets in CLI mode.
2. Add new critical anomaly detectors in `src/monag/autodiagnosis.py`:
   - `GIT_CONFLICT_MARKERS`: detect unresolved Git merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in source files (Tier: `floor`, Priority: `critical`).
   - `BROKEN_VENV`: detect broken Python virtualenvs (missing python interpreter or broken symlink) in projects with `pyproject.toml` (Tier: `floor`, Priority: `critical`).
3. Implement automated GitHub Issues synchronization in `autodiagnosis.py` (`sync_planfile_github()`) and expose via:
   - CLI flag `--sync-github` on `monag autodiagnose`.
   - REST endpoint `POST /api/autodiagnosis/sync-github.json` in `src/monag/panel.py`.
4. Enhance web panel (`monag serve`) UI:
   - Add visual priority badges (colors matching `critical`, `high`, `medium`/`normal`, `low`).
   - Add interactive "sync with github" button.
   - Add expandable ticket details (displaying `verify_command` and acceptance criteria).
5. Add unit and integration tests covering the new anomaly detectors, CLI report passing, GitHub synchronization, and panel badges.

## Acceptance criteria

- [x] AC-01: `GIT_CONFLICT_MARKERS` and `BROKEN_VENV` anomalies are correctly detected with tier `floor`.
- [x] AC-02: `monag autodiagnose` in CLI mode passes full diagnostic context enabling SQLite persistence.
- [x] AC-03: `sync_planfile_github` invokes `planfile sync github` on projects with updated sprints.
- [x] AC-04: Panel UI renders priority badges and provides a GitHub sync trigger.
- [x] AC-05: All tests pass and `./project/governance-check.sh` reports `GOV-PASS`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

