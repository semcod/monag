# Ticket 112: MCP: diagnose terminated sessions and expose read-only fallback health

- **ID**: ticket-112
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-11

## Goal and scope

Diagnose terminated MCP sessions and expose read-only fallback health:
1. Add explicit session lifecycle tracking (`uninitialized`, `active`, `closed`, `terminated`) and graceful client reconnect support in `src/monag/mcp.py`.
2. Implement transport health reporting, server liveness diagnostics, and error resilience (catching tool/DSL exceptions so sessions don't terminate abruptly).
3. Expose documented bounded read-only CLI fallback guidance both via MCP (`monag_health` tool and `monag://health` resource) and via CLI (`monag mcp --health` / `--diagnose`).
4. Ensure separation of MCP transport health from local CLI health, and prevent mutation replay upon reconnect.
5. Add comprehensive unit tests in `tests/test_mcp.py`.

## Acceptance criteria

- [x] AC-01: Session lifecycle state machine (`uninitialized`, `active`, `closed`, `terminated`) with reconnect handling in `src/monag/mcp.py`.
- [x] AC-02: Resilience against unhandled tool/DSL exceptions preventing unexpected session termination.
- [x] AC-03: Expose `monag_health` tool and `monag://health` resource detailing transport health, request counters, error rates, and CLI fallback mappings.
- [x] AC-04: Add CLI entrypoint flags (`monag mcp --health` and `monag mcp --diagnose`) showing diagnostic report and bounded read-only fallback commands.
- [x] AC-05: Tests for closed sessions, client reconnect, exception containment, transport health, and decoupling of CLI health from MCP failures.
- [x] AC-06: 100% test pass and `./project/governance-check.sh` passes with zero errors and zero warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
