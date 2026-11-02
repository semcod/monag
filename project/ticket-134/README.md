# Ticket 134: integrate subactor-search code2logic and reflex into known tools and advise

- **ID**: ticket-134
- **Owner**: agent:ant
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-03

## Goal and scope

1. Add `subactor-search`, `code2logic`, `reflex`, `heyasa`, `willman`, `dockuri`, and `twinerd` to `KNOWN_TOOLS` in `src/monag/ecosystem.py`.
2. Add `src/monag/search_integration.py` to extract code intents from project ASTs (`function.toon`, `map.toon.yaml`, and Python source) via `subactor_search`.
3. Provide Liquid D1 (`d1:3b`) decision reranking for monag advisory recommendations.
4. Expose `search` runner discovery in `src/monag/advise.py`.
5. Add unit tests in `tests/test_ecosystem_tools.py`.

## Acceptance criteria

- [x] AC-01: `KNOWN_TOOLS` in `monag.ecosystem` includes `subactor-search`, `code2logic`, `reflex`, `heyasa`.
- [x] AC-02: `monag.search_integration` extracts code intents and supports Liquid D1 reranking with graceful fallback.
- [x] AC-03: `tests/test_ecosystem_tools.py` passes all unit tests.
