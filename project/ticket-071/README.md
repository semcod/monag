# Ticket 071: Isolate merge CLI regression from host home directory

- **ID**: ticket-071
- **Owner**: codex:monag-report-resume-20260919
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested completion of the report fixes and tasks. PR #78 merged at 8932ae3391e49e7b4f1d382c395b2a65c86f4dc1, but the subsequent protected OneDev run failed because test_cli_merge_subcommand assumes ~/github exists in its isolated HOME. Bind that test to its temporary fixture root. Keep the product root validation and mocked merge behavior unchanged; do not alter the separate advise ticket069.

## Acceptance criteria

- [x] AC-01: The existing merge CLI regression passes with an isolated HOME lacking github.
- [x] AC-02: Protected-equivalent unittest discovery, full pytest and governance pass.
- [ ] AC-03: Publish through fresh independent verification before deployment.

## Validation

Reproduced the original failure with HOME pointing to an empty temporary directory. With the fixture root passed explicitly, the protected-equivalent isolated unittest discovery passed 242 tests and full pytest passed 320 tests. Managed governance passed. GitHub Issue79 / Planfile PLF-013.
