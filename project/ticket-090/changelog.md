# Changelog: ticket-090

- fix(autodiagnosis): invoke SubLLM with valid application (`koru-agent`) and function (`nl-to-koru-dsl`) routes with fallback to `todo2code`
- feat(summary): add `monag summary` (and `monag day`) command aggregating Planfile daily completed work, queued tickets, and GitHub PR metrics
- feat(cli): register `summary` and `day` subcommands in CLI with `--json` and `--no-github` flags
- test(summary): add unit tests for SubLLM route invocation and daily summary reporting in `tests/test_summary_and_subllm_routes.py`
