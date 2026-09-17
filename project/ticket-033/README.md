# Ticket 033: Add monag usage command reporting agent and account usage

- **ID**: ticket-033
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked whether a `monag usage`
command can show, in one table, the usage and account status of all agents,
after confirming that monag observes processes correctly but reports no usage
dimensions.

## Goal and scope

Add a read-only `monag usage` subcommand that renders one table per observed
usage source:

- **Agents** — every recognized agent process tree with PID, kind, state,
  children, working directory, cumulative tree CPU seconds, resident memory
  (summed `statm` pages) and uptime (btime + start jiffies), sorted by tree
  CPU. No prompts, environment variables or file contents are read.
- **Accounts** — `subactor.api-budget-state/v1` ledgers declared through
  repeatable `--ledger` sources: a state file, a directory glob of
  `api-budget-*.json`, `docker:CONTAINER` (read-only `docker exec` cat), or
  `docker:auto` (coordinator containers on this host). Each row shows provider,
  remaining budget, reset countdown or expiry, last decision and source.

Non-goals: no writes, no ledger mutation, no LLM token accounting (no local
source exists), no changes to `status`/`watch` rendering.

## Acceptance criteria

- [ ] AC-01: `monag usage` prints the agents table with CPU, memory and uptime
      for every detected agent.
- [ ] AC-02: `--ledger` sources produce one account row per valid ledger and a
      named observation error per malformed or unreachable source.
- [ ] AC-03: output honors `--json`, `--markdown`, `--plain`, `--machine`,
      `--all-users` and `--limit`; the interactive shell gains a `usage`
      command.
- [ ] AC-04: focused and full test suites plus the governance gate pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
