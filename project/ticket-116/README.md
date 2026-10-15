# ticket-116 — Independent publication adapter

- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Agent**: codex

Authorization: SESSION_EXECUTION_AUTHORIZATION — use Monag/Reflex, repair recurring Maskservice system errors, continue testing and protected merging for GitHub repositories. On-premise audit only.

## Outcome
Monag currently defaults to personal gh --admin and can switch to a browser session after an API failure. Route publication through a pinned independent adapter with exact repository, PR, ticket and head bindings. This closes an observed unsafe tool path; no evidence establishes Monag as the cause of the four owner-merge gaps.

## Acceptance
- AC-01: All merge entrypoints reject admin/browser overrides; missing, malformed, symlinked or wrong-digest host configuration cannot execute an adapter. Candidate config is not discovered. API/rate failures and adapter refusal remain blocked with no fallback.
- AC-02: Tests prove actual frozen head/ticket forwarding, trusted environment handling, success readback and moved-head refusal. Relevant tests, lint and governance pass.
- AC-03: Independent Validator approves and merges the frozen material source head before installing it. Host configuration selects independently published adapter bytes and protected environment; it contains no credentials.

Use the already reserved native allocator ticket-116, canonical Worktrees v5 planner and existing external ChangeLeaseStore. Do not invent an ID or manually author a controller lease.
