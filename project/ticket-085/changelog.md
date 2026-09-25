# Changelog: ticket-085

- feat(autodiagnosis): implement fleet autodiagnosis engine with SubLLM ticket synthesis and direct Planfile dispatch
- feat(cli): add `autodiagnose` subcommand supporting `--subllm`, `--no-subllm`, `--emit-planfile`, and `--feed-planfile`
- feat(panel): add autodiagnosis dashboard, REST endpoints, and daily Koru autonomous task delegation to `monag panel`
- test(autodiagnosis): add comprehensive unit and integration test suite covering fleet inspection, SubLLM synthesis, Planfile sprint storage, GitHub sync schema, and Koru autonomous handoff contracts
