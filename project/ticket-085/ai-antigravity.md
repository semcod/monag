# AI Antigravity Report: ticket-085

- Implemented `monag.autodiagnosis` module combining fleet diagnostics, SubLLM ticket synthesis, and Planfile sprint dispatching.
- Added support for SubLLM invocation via Python import (`subllm.complete`), workspace resolution, or CLI, with resilient deterministic rule fallback.
- Added Koru Autonomous handoff directives (`planfile ticket done`, git discipline) and Acceptance Criteria formatting (`AC-01`, `AC-02`) ready for `planfile sync github` and `koru.queue`.
- Exposed `monag autodiagnose` CLI command with `--subllm`, `--no-subllm`, `--emit-planfile`, and `--feed-planfile`.
- Implemented and verified comprehensive test suite in `tests/test_autodiagnosis_subllm_pipeline.py`.
