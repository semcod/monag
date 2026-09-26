# Ticket 097: Remove raw git url dependency from pyproject.toml

- **ID**: ticket-097
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

1. Resolve autodiagnosis CRITICAL item: `fix(dependency-git-url-found)`. Remove raw `subactor-procache @ git+https://...` from `pyproject.toml`'s `project.dependencies`.
2. Ensure standard PEP 508 / PEP 440 packaging compliance for `monag`.
3. Verify that `monag autodiagnose` no longer detects `DEPENDENCY_GIT_URL_FOUND`.

## Acceptance criteria

- [x] AC-01: Remove `subactor-procache` git URL from `pyproject.toml`.
- [x] AC-02: `pyproject.toml` remains valid and installs cleanly.
- [x] AC-03: Governance checks pass (`GOV-PASS`) with delivery contract.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
