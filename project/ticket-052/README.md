# Ticket 052: Unified API with NL DSL, MCP Server, and REST Endpoints

- **ID**: ticket-052
- **Owner**: tom
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested unified API for CLI shell, REST API, MCP with NL DSL)

## Goal and scope

Extract and unify the observation capabilities of monag across three delivery surfaces:
1. **NL DSL (`src/monag/dsl.py`)**: A rule-based parser that maps natural language statements (in Polish and English) into a structured DSL (`OBSERVE <domain> ...`) and dispatches them directly to the underlying domain modules (`prs`, `audit`, `monitor`, `resume`, `usage`, `catalog`).
2. **MCP Server (`src/monag/mcp.py`)**: A Model Context Protocol server communicating over stdio JSON-RPC 2.0, exposing tools (`monag_status`, `monag_prs`, `monag_audit`, `monag_resume`, `monag_usage`, `monag_catalog`, `monag_query`) and resources (`monag://snapshot`, `monag://prs`, `monag://audit`, `monag://resume`).
3. **REST API (`src/monag/panel.py`)**: Add `/api/prs.json` and `/api/query` to the local HTTP server.
4. **Shell and CLI Integration (`src/monag/cli.py`)**: Add `monag mcp` CLI command and enable natural language input directly in `monag shell`.

## Acceptance criteria

- [x] AC-01: `src/monag/dsl.py` parses natural language phrases (PL/EN) into structured queries and executes them cleanly.
- [x] AC-02: `src/monag/mcp.py` implements the Model Context Protocol (JSON-RPC 2.0 stdio) exposing tools and resources.
- [x] AC-03: `monag mcp` command is available from CLI to run the MCP server.
- [x] AC-04: `src/monag/panel.py` serves `/api/prs.json` and `/api/query` (POST/GET for NL & DSL queries).
- [x] AC-05: `monag shell` recognizes natural language commands and executes them via the DSL engine.
- [x] AC-06: Comprehensive unit tests in `tests/test_dsl.py`, `tests/test_mcp.py`, and `tests/test_panel.py` pass cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent.
