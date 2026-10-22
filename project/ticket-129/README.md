# Ticket 129: Preserve ticket radar in Planfile ticket exports

- **ID**: ticket-129
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested “kontynuuj, wdrazaj dla tickets”. Preserve bounded advisory radar metrics in Monag recommendation-to-Planfile descriptions so existing create/update tracker synchronization publishes them. Invoke protected publication and install the reviewed local runtime after validation. Keep absent/invalid radar compatible; do not export raw untrusted fields or change ticket authority, priority, or lifecycle.

## Acceptance criteria

- [x] AC-01: A valid radar keeps complexity, score, estimated minutes and split recommendation in the exported ticket description.
- [x] AC-02: Missing or invalid radar leaves legacy descriptions unchanged; unknown text and fields cannot inject Markdown or leak into tickets.
- [x] AC-03: Import/persistence and create/update GitHub projection retain the description without overwriting external human content.
- [ ] AC-04: Focused and repository tests pass; protected PR review/merge and installed runtime readback are recorded separately.

## Validation evidence

61 focused tests passed with one existing skip. A real installed Planfile CLI imported the normalized list, persisted the advisory description, and read it back. The real GitHubBackend description merger preserved human notes and updated a single radar section. Wheel build passed. The broad run passed 537 tests with one skip; 14 environment failures were isolated to subprocess import paths and missing optional procache. All 14 passed after supplying the worktree source path and the existing immutable procache dependency release (6 + 8 reruns). Protected publication and reviewed runtime installation remain pending.
