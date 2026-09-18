# Ticket 059: monag report: periodic email digest of workspace activity

- **ID**: ticket-059
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested periodic task execution report generator with email)

## Goal and scope

Add `monag report` subcommand to deliver periodic Markdown/HTML workspace activity digests via email:
1. Collect data from existing monag scan modules (snapshot, audit, resume, prs, export)
2. Format as Markdown and HTML email
3. Send via SMTP (configurable host/port/credentials via flags and MONAG_SMTP_* env vars)
4. Support crontab management (--install-cron / --remove-cron) for periodic execution
5. Support dry-run mode (--dry-run) and JSON output (--json)

## Acceptance criteria

- [x] AC-01: `monag report` collects data from requested sections (default: status, prs, audit, resume, export).
- [x] AC-02: Formats readable Markdown and HTML email digest.
- [x] AC-03: Sends email via SMTP using standard library `smtplib` and `email` (no new dependencies).
- [x] AC-04: Supports `--install-cron` and `--remove-cron` for scheduling hourly runs via system crontab.
- [x] AC-05: `--dry-run` prints the report without sending email.
- [x] AC-06: Comprehensive unit tests pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
