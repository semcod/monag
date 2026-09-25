# Changelog: ticket-089

- feat(autodiagnosis): detect `GIT_CONFLICT_MARKERS` and `BROKEN_VENV` critical anomalies with tier `floor`
- feat(cli): pass full diagnostic report into `synthesize_tickets_with_subllm` enabling SQLite cache persistence in CLI mode
- feat(cli): add `--sync-github` and `--dispatch` flags to `monag autodiagnose`
- feat(panel): add priority badges and expandable verification details to `monag serve`
- feat(panel): add `POST /api/autodiagnosis/sync-github.json` endpoint and interactive button in web panel
- test(autodiagnosis): add comprehensive tests for new anomaly detectors and GitHub sync
