# Ticket 065: monag report: email 1-click configuration links for frequency, persistent report_config, and settings UI

- **ID**: ticket-065
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested investigation and ability to change report frequency and config via links in the email)

## Goal and scope

1. Add persistent `report_config.json` in `state_dir` with `load_config()` and `save_config()`.
2. Support 1-click email footer preset links for changing delivery frequency (30m, 1h, 2h, 4h, 24h) and opening settings UI.
3. In `monag panel`, provide:
   - `/api/report/config` (GET / POST) to query or update interval, schedule, email, sections, and enabled flag.
   - `/report/config` serving an interactive HTML settings page for browsers.
   - User-friendly HTML confirmation when changing settings via 1-click links directly from an email client.
4. Dynamically adapt `report.run_daemon()`: reloads `report_config.json` on every iteration so frequency adjustments take effect immediately without restarting the process.
5. 100% test coverage and governance compliance.

## Acceptance criteria

- [x] AC-01: `report.load_config()` and `report.save_config()` handle persistent configuration.
- [x] AC-02: `report.footer_management_markdown()` includes 1-click frequency preset URLs.
- [x] AC-03: `panel.py` routes `/api/report/config` and `/report/config` render interactive HTML and return JSON.
- [x] AC-04: `report.run_daemon()` dynamically reloads config on each loop cycle.
- [x] AC-05: Comprehensive unit tests pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
