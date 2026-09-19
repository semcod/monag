# Ticket 068: adopt wellmanifest docs standard and deduplication

- **ID**: ticket-068
- **Owner**: agent:gemini
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19

## Goal and scope

Adopt `wellmanifest/docs` standard in `semcod/monag` at the latest pinned revision. Add `.governance/docs.json`, conform `docs/` and `docs/README.md` to policy-as-code documentation and deduplication standards (DOCS-001 through DOCS-013), and verify clean governance and test passes.

## Acceptance criteria

- [x] AC-01: Add `.governance/docs.json` pinning `wellmanifest/docs@d3b63df4d5386fecaa6b3cbb7b607068593d8434` with valid `policy_sha256`.
- [x] AC-02: Ensure `docs/` conform to the schema with valid metadata and complete section markers.
- [x] AC-03: Pass `docs/standard/check.py` from `wellmanifest/docs`.
- [x] AC-04: Pass `./project/governance-check.sh` and pytest test suite.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
