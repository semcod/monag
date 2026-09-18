# Ticket 053: resilient REST fallback for gh PR query

- **Owner**: agent:Antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-18

## Goal and scope

Add robust GitHub REST API fallback (`gh api repos/<repo>/pulls`) to `monag prs` when `gh pr list` fails (e.g. due to GitHub GraphQL secondary rate limits or errors). This ensures `monag prs` and `monag audit` always retrieve pull requests accurately across workspace repositories.

## Acceptance criteria

- [x] AC-01: `github_open_prs` in `src/monag/prs.py` falls back to `gh api repos/<repo>/pulls` if `gh pr list` fails.
- [x] AC-02: REST payload is normalized to the standard PR schema (`number`, `title`, `headRefName`, `baseRefName`, `url`, `isDraft`, `state`, `author`, `updatedAt`, `createdAt`, `mergedAt`).
- [x] AC-03: Add unit tests verifying both primary `gh pr list` and fallback REST behavior.
- [x] AC-04: All test suite tests pass and `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
