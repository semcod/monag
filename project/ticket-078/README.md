# Ticket 078: MCP observation contract

- **ID**: ticket-078
- **Owner**: codex-monag-mcp-20260919
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19
- **Planfile**: PLF-028
- **Issue**: https://github.com/semcod/monag/issues/95

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuation after the installed MCP assessment, under the existing fix/publication authorization. Adopt the read-only observation interface from wellmanifest/nl-dsl-llm at 2040efe37b9eb898350f3fec0285a2d4e69d4e34. Implement execute_dsl, nl_ask, describe_grammar, schema://current, standard structured results and correct error propagation, with one validated observation executor including advisory queries. Scope is disjoint from ticket-076 and the concurrent governance adoption ticket-077. No claim of full mutation-interface conformance or client MCP registration.

## Acceptance criteria

- [x] AC-01: Standard MCP tools/resource and shared CLI/REST observation entrypoints preserve provenance, validate commands, reject malformed DSL and emit correct errors; legacy tool names remain usable.
- [ ] AC-02: Regression/full suite and governance pass; independent protected publication and installed-runtime canaries succeed.

## Standard source

The immutable source, supported schema profile and invocation examples are returned by describe_grammar and schema://current; source and tests are the material deliverables.

## Validation

Final full application run: 362 tests and 30 subtests passed, including twelve conformance tests covering CLI compatibility and rejected LLM translation provenance. The pinned normative command/result schemas independently validate real success and error envelopes; the advertised observation schema is valid JSON Schema. Ruff on all changed Python files and governance pass. Protected review and installed-runtime validation remain external delivery receipts.
