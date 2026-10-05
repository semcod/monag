# Ticket 100: Dynamic tool and API discovery in monag doctor and tools command

- **ID**: ticket-100
- **Owner**: antigravity
- **Status**: DONE
- **Workflow state**: COMPLETE
- **Created**: 2026-09-28

## Goal and scope

Enhance ecosystem discovery in `monag`:
1. Expand tool auditing in `monag doctor` and `monag tools` from a static 5-element map to dynamic discovery of all installed ecosystem tools (CLI binaries in PATH, Python entrypoints, semcod/wellmanifest capabilities).
2. Add a new `monag tools` (and `monag apis`) CLI command to audit and present detected ecosystem tools, their executables, availability, versions/roles, and active local daemon services (SubLLM, Koru lanes, MCP servers).
3. Provide robust programmatic discovery helper `src/monag/ecosystem.py` for CLI, doctor, panel, and autonomous agents to query available tooling.

## Acceptance criteria

- [x] AC-01: Implement `src/monag/ecosystem.py` discovering CLI tools, python entrypoints, and active local daemon services/ports.
- [x] AC-02: Update `monag doctor` to utilize the dynamic ecosystem discovery while preserving backwards compatibility.
- [x] AC-03: Add `monag tools` CLI command supporting text, markdown, and JSON output formats.
- [x] AC-04: Add comprehensive tests in `tests/test_ecosystem_tools.py` verifying detection, CLI invocation, and fallbacks.
- [x] AC-05: Ensure 100% test pass and zero governance violations (`GOV-PASS`).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
