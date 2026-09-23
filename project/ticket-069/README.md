# Ticket 069: feat(advise): Holistic algorithmic workspace triage and step-by-step guidance engine

- **ID**: ticket-069
- **Owner**: human:founder
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-09-19
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user requested algorithmic workspace triage and guidance engine in monag)

## Goal and scope

Implement a holistic, algorithmic workspace triage and direction synthesis engine in `monag advise` capable of scanning the full multi-organization ecosystem (4,200+ repos, active agents, unmerged PRs, dirty checkouts, and issue backlogs) and generating deterministic, prioritized, step-by-step guidance.

## Acceptance criteria

- [x] AC-01: Implement `monag.triage` / `monag advise --holistic` spanning multi-org repository discovery, running agent collision detection, and issue classification.
- [x] AC-02: Algorithmic ranking separating immediate blockers (critical disk/health alerts), core personal repos, strategic architecture tickets, and code-smell quality tasks.
- [x] AC-03: Deterministic step-by-step guidance exportable to markdown, JSON, and Planfile backlog/sprint ingestion.
- [x] AC-04: Full test coverage with automated unit tests for candidate sorting, collision prevention, and failure-pattern integration.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
