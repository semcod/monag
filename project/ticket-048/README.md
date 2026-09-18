# Ticket 048: codex exact session resume

- **ID**: ticket-048
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: continue the numbered improvement list —
extend exact-session resume to codex.

## Goal and scope

- `codex` today resumes the globally-newest session (`codex resume`), which
  picks the wrong conversation when several codex instances run at once.
- Resolve the running instance's own session the same way tickets 045/046
  did for agy/claude/opencode: read `/proc/<pid>/fd` symlink targets for
  `*/sessions/**/rollout-*.jsonl` (codex holds its rollout file open) and
  resume `codex resume <uuid>`. Paths only — never file contents.
- Fallback when no fd matches: bare `codex resume` recipe stays.
- Other kinds unchanged. Read-only observation.

## Verification

- `tests/test_opener.py` covers fd rollout discovery, uuid extraction and
  the no-match fallback on fake `/proc` fixtures.
- `./project/governance-check.sh` clean.
