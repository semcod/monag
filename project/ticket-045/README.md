# Ticket 045: per-session resume from process open files

- **ID**: ticket-045
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: continue improving `monag open` so it
resumes the exact running session instead of the newest conversation in
the directory.

## Goal and scope

- `agy` family: read `/proc/<pid>/fd` symlink targets for
  `*/conversations/<uuid>.db` and open `agy --conversation <uuid>`.
  Reads paths only — never file contents, prompts or env.
- `claude`: best-effort newest `*.jsonl` in
  `~/.claude/projects/<cwd-slug>` → `claude --resume <id>` (claude does
  not hold the session file open).
- Both fall back to the previous `--continue` recipe when no session can
  be identified; other kinds unchanged.
- `proc`/`home` parameters threaded through `recipe`/`open_agent`/
  `open_target`/`open_interactive` for testability.

## Verification

- `tests/test_opener.py` covers fd discovery, fallback and the claude
  newest-file heuristic on fake `/proc` and home fixtures.
- `./project/governance-check.sh` clean.
