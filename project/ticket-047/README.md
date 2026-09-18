# Ticket 047: attach to running opencode http server

- **ID**: ticket-047
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: continue the numbered improvement list —
browser/attach route to a live agent server.

## Goal and scope

- Detect a running agent's HTTP listener: `/proc/<pid>/fd` socket inodes
  matched against `net/tcp` LISTEN entries (paths/ports only, no traffic).
- `opencode` terminal action: when the process listens, prefer
  `opencode attach http://host:port` — a TUI client attached to the live
  server — over the `--session <id>` resume and the bare fallback.
- `opencode` browser action: when the process listens, `xdg-open` the
  live URL directly instead of spawning a new `opencode web` server.
- Scope is opencode-only; other kinds unchanged. Read-only observation.

## Verification

- `tests/test_opener.py` covers inode→port resolution, the attach recipe,
  the live-URL browser route and the no-listener session fallback on
  fake `/proc` fixtures.
- `./project/governance-check.sh` clean.
