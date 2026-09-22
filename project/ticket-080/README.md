# Ticket 080: fix-advise-guidelines-repo-none-type-error

- **ID**: ticket-080
- **Owner**: human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-22

## Goal and scope

Fix TypeError (`TypeError: argument of type 'NoneType' is not iterable`) in `monag.advise.synthesize_guidelines` occurring when a candidate item has `repo: None`. Ensure `repo` safely defaults to empty string before substring/membership checks.

## Acceptance criteria

- [x] AC-01: Safely handle `None` repo/path values in `monag.advise.synthesize_guidelines`.
- [x] AC-02: Add unit test verifying `synthesize_guidelines` handles `repo: None` without raising TypeError.
- [x] AC-03: Pass all tests in `tests/test_advise.py` and governance check with `GOV-PASS`.

## Validation

All 26 tests in `tests/test_advise.py` passed. Governance check passed with 0 errors, 0 warnings.
