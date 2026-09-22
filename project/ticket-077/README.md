# Ticket 077: Adopt wellmanifest/new-project 0.20.32

- **ID**: ticket-077
- **Owner**: unresolved:human
- **Status**: DONE
- **Workflow state**: PUBLISHED
- **Created**: 2026-09-19

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: adopt, test, push and protected merge of wellmanifest/new-project 0.20.32 in semcod/monag.

Adopt published standard `0.20.32` (`b6ba9c21a65a6a5648ecf904b64c3b75295e136f`), replacing `0.20.31` (`2b016654cff1a1ccef2c0d6126a9c2550ae6b37a`). Fix pytest `pythonpath` in `pyproject.toml` to include the repository root `"."` so `wellmanifest_governance` imports cleanly under standard pytest invocations.

## Acceptance criteria

- [x] AC-01: Adopt standard revision `b6ba9c21a65a6a5648ecf904b64c3b75295e136f`, regenerating lock and package manifests.
- [x] AC-02: Synchronize `[tool.wellmanifest]` in `pyproject.toml` to standard `0.20.32` and revision `b6ba9c21a65a6a5648ecf904b64c3b75295e136f`.
- [x] AC-03: Add `"."` to `[tool.pytest.ini_options].pythonpath` in `pyproject.toml`.
- [x] AC-04: Harmonize coordination workstream definitions in `.governance/manifest.json`.
- [x] AC-05: Pass test suite and governance check with `GOV-PASS`.
