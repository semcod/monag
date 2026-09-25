# Ticket 088: integrate wellmanifest priority sorting and todo2code verification in autodiagnosis

- **ID**: ticket-088
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-25

## Goal and scope

1. Integrate `wellmanifest/priority` lexicographic tier ordering (`critical/floor` > `high/mission` > `medium/hygiene` > `low/backlog`) into `monag autodiagnose` Planfile sprint generator (`src/monag/autodiagnosis.py`).
2. Implement task enrichment with `todo2code` conventions (`inputs.verify_command`, `inputs.contract`, labels `type:development-defect`, `source.todo2code`) so Koru Autonomous can immediately hydrate and autonomously verify defects using `run_next_planfile_task`.
3. Ensure tickets emitted to Planfile sprints (`.planfile/sprints/sprint-YYYYMMDD.yaml`) are deterministically sorted by tier/priority and created_at.
4. Ensure web panel (`monag serve`) displays tasks according to the priority tier.
5. Add unit and integration tests covering priority sorting and todo2code verification fields.

## Acceptance criteria

- [x] AC-01: `sort_tickets_by_priority()` sorts tasks using lexicographic tiers (`floor` > `mission` > `hygiene` > `backlog`) and priority order (`critical` > `high` > `normal`/`medium` > `low`).
- [x] AC-02: Tasks synthesized by autodiagnosis populate `verify_command` (e.g. pytest or status check) and appropriate defect labels for Koru.
- [x] AC-03: Planfile sprint YAML exports tasks ordered by priority.
- [x] AC-04: Full test coverage in `tests/test_priority_and_todo2code_integration.py` passing with 100% success.
- [x] AC-05: `./project/governance-check.sh` reports `GOV-PASS`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

