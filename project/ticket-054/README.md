# Ticket 054: normative specification and reference implementation for NL-DSL-LLM

- **ID**: ticket-054
- **Owner**: agent:opencode
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested continuation of the ticket series)

## Goal and scope

Add a normatively specified LLM fallback layer for the Monag natural-language
query DSL (introduced in ticket-052):

1. **Normative specification** (`docs/information/nl-dsl-llm.md`): the binding
   contract for NL-DSL-LLM translation — rule engine first, LLM only as
   fallback, provider invocation protocol, output validation, provenance and
   failure semantics.
2. **Reference implementation** (`src/monag/dsl_llm.py`): `resolve()` /
   `execute()` that try the rule-based `monag.dsl` parser first and, when it
   cannot map the input and an LLM command is configured, ask a configured
   provider to emit exactly one canonical `OBSERVE ...` line which is validated
   through `monag.dsl.parse_dsl` before execution. No LLM is contacted unless
   `MONAG_LLM_COMMAND` is set; default behavior is unchanged.
3. **Integration**: `monag query`, `monag shell`, panel `/api/query` and the
   MCP `monag_query` tool route unrecognized natural language through the
   bridge and report the translation provenance.

## Acceptance criteria

- [ ] AC-01: `docs/information/nl-dsl-llm.md` specifies the NL-DSL-LLM contract (grammar, provider protocol, validation, provenance, failure semantics) with Wellmanifest Docs metadata.
- [ ] AC-02: `src/monag/dsl_llm.py` resolves rule-parser successes locally (engine `rule`, no subprocess) and maps rule-unmappable input via the configured provider to a `parse_dsl`-validated Query.
- [ ] AC-03: LLM output that is empty, fenced, multi-statement or unparseable is rejected; no best-effort execution of raw model output occurs.
- [ ] AC-04: `monag query`, shell, `/api/query` (GET+POST) and MCP `monag_query` use the bridge and expose `provenance` in JSON results.
- [ ] AC-05: Unit tests in `tests/test_dsl_llm.py` cover rule-first short-circuit, provider translation, rejection paths, timeout and disabled-by-default behavior; the full suite passes.
- [ ] AC-06: `./project/governance-check.sh` passes with the material delta on the ticket branch.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
