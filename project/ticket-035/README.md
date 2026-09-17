# Ticket 035: detect antigravity and additional agent CLIs

- **ID**: ticket-035
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user reported that `monag usage` does
not detect antigravity (`agy` CLI shell) and other agent processes running on
this host.

## Goal and scope

Extend the executable registry in `src/monag/agents.py` so the process scan
recognizes agent CLIs installed on this host that were previously invisible:

- `agy`, `agy2`, `agy-coding-agent` — Google Antigravity CLI and its wrappers.
- `agent` — the Grok agent binary (`~/.grok/bin/agent`).
- `tiny-agents` — Hugging Face MCP agent runner.

IDE host processes (`antigravity-ide`, `devin-desktop`) stay undetected: they
host agent sessions but are not agent sessions themselves.

## Acceptance criteria

- [ ] AC-01: `identify()` returns a kind for `agy`, `agy2`,
      `agy-coding-agent`, `agent` and `tiny-agents` argv forms.
- [ ] AC-02: `monag usage` lists running `agy` processes.
- [ ] AC-03: focused and full test suites plus the governance gate pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
