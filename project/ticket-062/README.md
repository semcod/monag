# Ticket 062: monag report: auto-detect GitHub email, hourly daemon, and footer management links/endpoints

- **ID**: ticket-062
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested auto-resolving email from gh/git, hourly reporting, and management footer links/commands)

## Goal and scope

1. Auto-detect user email when not explicitly passed:
   - Check `gh api user --jq .email`
   - Fall back to `git config --get user.email`
   - Fall back to `os.environ.get('MONAG_EMAIL')` or `os.environ.get('EMAIL')`
2. Add management footer to `monag report` (Markdown & HTML):
   - Instructions and exact CLI commands to modify schedule, recipient, sections, or disable.
   - Clickable local URLs linking to the running `monag panel` host (e.g. `http://127.0.0.1:8090`).
3. Add report endpoints to `monag panel` (`src/monag/panel.py`):
   - `/api/report/status`: view report configuration, recipient, and scheduler status.
   - `/api/report/disable`: 1-click disable/remove report schedule.
   - `/api/report/send-now`: trigger an immediate report run.
4. Add `--daemon` and `--interval` flags to `monag report` for headless container / user-space scheduling without needing root crontab.
5. 100% tests pass and governance pass.

## Acceptance criteria

- [x] AC-01: `report.detect_user_email()` resolves email from `gh` or `git config`.
- [x] AC-02: `monag report` defaults to detected email if `--email` is omitted.
- [x] AC-03: `report.markdown()` and email body include management footer with CLI commands and panel URLs.
- [x] AC-04: `src/monag/panel.py` exposes `/api/report/status`, `/api/report/disable`, and `/api/report/send-now`.
- [x] AC-05: `monag report` supports `--daemon` and `--interval` for continuous in-process scheduling.
- [x] AC-06: Unit tests cover email detection, footer generation, daemon cycle, and panel endpoints.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
