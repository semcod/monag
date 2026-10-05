# Ticket 103: fix(autodiagnosis): avoid false positive conflict markers on decorative separator lines

- **ID**: ticket-103
- **Owner**: unresolved:human
- **Status**: DONE
- **Workflow state**: COMPLETE
- **Created**: 2026-10-03

## Goal and scope

Refine Git merge conflict marker detection in `monag.autodiagnosis` to prevent false positive `GIT_CONFLICT_MARKERS` warnings on decorative separator lines (such as 80-character equals headers in LICENSE or markdown files).

## Acceptance criteria

- [x] AC-01: Git conflict marker regex is constrained to true marker boundaries `^(<{7} |={7}$|>{7} )`.
- [x] AC-02: Unit tests verify both detection of actual conflict markers and exclusion of decorative separator lines.
- [x] AC-03: Governance checks pass with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
